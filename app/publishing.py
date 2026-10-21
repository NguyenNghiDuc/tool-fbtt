import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import httpx
from fastapi import Depends, HTTPException

class PublishError(Exception):
    def __init__(self, code, retry=False, uncertain=False):
        self.code, self.retry, self.uncertain = code, retry, uncertain
        super().__init__(code)

def install(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event):
    with db.connect() as conn:
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(jobs)')}
        if 'started' not in columns:
            conn.execute('ALTER TABLE jobs ADD COLUMN started INTEGER')
        if 'processing_since' not in columns:
            conn.execute('ALTER TABLE jobs ADD COLUMN processing_since INTEGER')
            conn.execute("UPDATE jobs SET processing_since=COALESCE(started,created) WHERE status='processing'")
    processing_timeout = int(cfg.get('PROCESSING_TIMEOUT_SECONDS', '1800'))
    if not 60 <= processing_timeout <= 86400:
        raise RuntimeError('PROCESSING_TIMEOUT_SECONDS must be between 60 and 86400')
    from .reconciliation import install as reconciliation
    reconciliation(app, db, publisher)
    semaphore = asyncio.Semaphore(4)
    tick_lock = asyncio.Lock()
    async def call(method, url, **kwargs):
        try:
            async with httpx.AsyncClient(transport=app.state.providers.transport, timeout=120) as client:
                response = await client.request(method, url, **kwargs)
            if response.status_code == 429:
                raise PublishError('rate_limited', retry=True)
            if response.status_code in (401, 403):
                raise PublishError('authorization_revoked')
            if response.status_code >= 500:
                raise PublishError('platform_server_error', uncertain=method != 'GET', retry=method == 'GET')
            if response.status_code >= 400:
                raise PublishError('platform_rejected')
            if not response.content:
                return {}
            data = response.json()
            error = data.get('error')
            if error and (not isinstance(error, dict) or error.get('code') not in (None, 'ok')):
                raise PublishError('platform_rejected')
            return data
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise PublishError('network_connect_failed', retry=True) from None
        except (httpx.HTTPError, ValueError):
            raise PublishError('network_outcome_unknown', uncertain=method != 'GET', retry=method == 'GET') from None
    def finish(job, remote, expected='publishing'):
        status = 'manual_link' if get_profile(job['profile_id'])['platform'] == 'tiktok' else 'success'
        with db.connect() as conn:
            changed = conn.execute('''UPDATE jobs SET status=?,remote_id=?,error=NULL,processing_since=NULL
                WHERE id=? AND status=?''', (status, remote, job['id'], expected)).rowcount
            if not changed:
                return
            conn.execute('UPDATE assignments SET used=1 WHERE media_id=? AND profile_id=?', (job['media_id'], job['profile_id']))
        event('publish_success', job['profile_id'], f'Job {job["id"]}: {status}')
    async def send(job):
        p, media = get_profile(job['profile_id']), get_media(job['media_id'])
        if not p['access_token'] or p['token_status'] != 'connected':
            raise PublishError('token_not_connected')
        if p['expires'] and p['expires'] <= time.time():
            raise PublishError('token_expired')
        product = app.state.find_record('product', job['product_id'])
        if not product['available']:
            raise PublishError('product_unavailable')
        token = app.state.cipher.decrypt(p['access_token'].encode()).decode()
        headers = {'Authorization': 'Bearer ' + token}
        if p['platform'] == 'facebook':
            base = f'https://graph.facebook.com/{cfg["FACEBOOK_API_VERSION"]}'
            # Verify a previously non-expiring Page token before publishing.
            identity = await call('GET', base + '/me', headers=headers, params={'fields': 'id'})
            if identity.get('id') != p['external_id']:
                raise PublishError('account_mismatch')
            with Path(media['path']).open('rb') as video:
                data = await call('POST', base + '/' + p['external_id'] + '/videos', headers=headers,
                    data={'description': job['caption']}, files={'source': (media['name'], video, 'video/mp4')})
            if not data.get('id'):
                raise PublishError('missing_remote_id', uncertain=True)
            finish(job, data['id'])
            return
        creator = await call('POST', 'https://open.tiktokapis.com/v2/post/publish/creator_info/query/', headers=headers, json={})
        creator = creator.get('data', {})
        if 'SELF_ONLY' not in creator.get('privacy_level_options', []):
            raise PublishError('private_post_not_allowed')
        metadata = json.loads(media['metadata'])
        if metadata['duration'] > creator.get('max_video_post_duration_sec', 0):
            raise PublishError('video_exceeds_creator_limit')
        size = Path(media['path']).stat().st_size
        # A single-chunk upload supports up to 64 MiB. Larger files need the chunked adapter.
        if size > 64 * 1024 * 1024:
            raise PublishError('tiktok_single_chunk_limit_64mib')
        data = await call('POST', 'https://open.tiktokapis.com/v2/post/publish/video/init/', headers=headers, json={
            'post_info': {'title': job['caption'], 'privacy_level': 'SELF_ONLY',
                          'disable_duet': True, 'disable_stitch': True, 'disable_comment': False,
                          'brand_content_toggle': True, 'brand_organic_toggle': False},
            'source_info': {'source': 'FILE_UPLOAD', 'video_size': size, 'chunk_size': size, 'total_chunk_count': 1}})
        data = data.get('data', {})
        remote, upload_url = data.get('publish_id'), data.get('upload_url', '')
        parsed = urlparse(upload_url)
        if not remote or parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.tiktokapis.com') or parsed.username or parsed.port not in (None, 443):
            raise PublishError('invalid_upload_destination', uncertain=True)
        # Save the remote reference before uploading so status can be reconciled after a crash.
        db.execute('UPDATE jobs SET remote_id=? WHERE id=?', (remote, job['id']))
        with Path(media['path']).open('rb') as video:
            content = video.read()
        await call('PUT', upload_url, content=content, headers={'Content-Type': 'video/mp4',
            'Content-Length': str(size), 'Content-Range': f'bytes 0-{size-1}/{size}'})
        db.execute("UPDATE jobs SET status='processing',processing_since=? WHERE id=? AND status='publishing'",
                   (int(time.time()), job['id']))
        event('publish_processing', p['id'], f'Job {job["id"]}: awaiting TikTok processing')
    async def run_one(job):
        async with semaphore:
            try:
                await send(job)
            except PublishError as exc:
                # An initialized TikTok upload is reconciled manually on transport failure.
                remote = db.query('SELECT remote_id FROM jobs WHERE id=?', (job['id'],))[0]['remote_id']
                uncertain = exc.uncertain or bool(remote)
                if uncertain:
                    state = 'uncertain'
                elif exc.retry and job['attempts'] < 3:
                    state = 'queued'
                else:
                    state = 'failed'
                db.execute('UPDATE jobs SET status=?,error=?,scheduled=? WHERE id=?',
                    (state, exc.code, int(time.time()) + 60 * 2 ** job['attempts'], job['id']))
                if exc.code in ('authorization_revoked', 'token_expired'):
                    db.execute("UPDATE profiles SET token_status='revoked' WHERE id=?", (job['profile_id'],))
                event('publish_error', job['profile_id'], f'Job {job["id"]}: {exc.code}; {state}')
            except Exception:
                # Never expose SDK messages, which can contain request URLs or tokens.
                db.execute("UPDATE jobs SET status='uncertain',error='internal_error_check_platform' WHERE id=?", (job['id'],))
                event('publish_error', job['profile_id'], f'Job {job["id"]}: internal_error_check_platform')
    def expire_processing():
        now = int(time.time())
        with db.connect() as conn:
            expired = conn.execute('''UPDATE jobs SET status='uncertain',error='processing_timeout_check_platform'
                WHERE status='processing' AND COALESCE(processing_since,started,created)<=?
                RETURNING id,profile_id''', (now - processing_timeout,)).fetchall()
            for job in expired:
                conn.execute('INSERT INTO events(kind,profile_id,message,created) VALUES (?,?,?,?)',
                    ('publish_error', job['profile_id'],
                     f'Job {job["id"]}: processing_timeout_check_platform; uncertain', now))

    async def poll():
        for job in db.query("SELECT * FROM jobs WHERE status='processing'"):
            p = get_profile(job['profile_id'])
            try:
                token = app.state.cipher.decrypt(p['access_token'].encode()).decode()
                data = await call('POST', 'https://open.tiktokapis.com/v2/post/publish/status/fetch/',
                    headers={'Authorization': 'Bearer ' + token}, json={'publish_id': job['remote_id']})
                state = data.get('data', {}).get('status')
                if state == 'PUBLISH_COMPLETE':
                    finish(job, job['remote_id'], expected='processing')
                elif state == 'FAILED':
                    db.execute("UPDATE jobs SET status='failed',error='tiktok_processing_failed' WHERE id=? AND status='processing'", (job['id'],))
                    event('publish_error', job['profile_id'], f'Job {job["id"]}: tiktok_processing_failed')
            except PublishError as exc:
                # Polling is read-only and can safely resume at the next tick.
                db.execute("UPDATE jobs SET error=? WHERE id=? AND status='processing'", (exc.code, job['id']))
                if job['error'] != exc.code:
                    event('publish_error', job['profile_id'], f'Job {job["id"]}: status_poll_{exc.code}')
                continue
            except Exception as exc:
                from .diagnostics import error_type
                code = 'status_poll_' + error_type(exc)
                db.execute("UPDATE jobs SET error=? WHERE id=? AND status='processing'", (code, job['id']))
                if job['error'] != code:
                    event('publish_error', job['profile_id'], f'Job {job["id"]}: {code}')
    def claim(now):
        claimed = []
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT value FROM settings WHERE key='paused'").fetchone()['value'] == 'true':
                return claimed
            for candidate in conn.execute("SELECT j.* FROM jobs j JOIN profiles p ON p.id=j.profile_id WHERE j.status='queued' AND j.scheduled<=? AND p.status='active' ORDER BY j.scheduled LIMIT 100", (now,)).fetchall():
                job = dict(candidate)
                if any(j['profile_id'] == job['profile_id'] for j in claimed):
                    continue
                if conn.execute("SELECT 1 FROM jobs WHERE profile_id=? AND status IN ('publishing','processing','uncertain')", (job['profile_id'],)).fetchone():
                    continue
                schedule = app.state.schedule_for(job['profile_id'])
                zone = ZoneInfo(schedule['timezone'])
                start = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                used = conn.execute("SELECT count(*) FROM jobs WHERE profile_id=? AND started>=? AND started<? AND status IN ('success','manual_link','publishing','processing','uncertain')", (job['profile_id'], int(start.timestamp()), int(end.timestamp()))).fetchone()[0]
                if used >= schedule['daily_limit']:
                    continue
                conn.execute("UPDATE jobs SET status='publishing',attempts=attempts+1,started=? WHERE id=? AND status='queued'", (now, job['id']))
                job['attempts'] += 1
                claimed.append(job)
        return claimed
    async def tick():
        if tick_lock.locked():
            return {'busy': True}
        async with tick_lock:
            # A deadline remains effective even with publishing disabled or the system paused.
            expire_processing()
            app.state.plan()
            if cfg.get('PUBLISH_ENABLED', 'false').lower() != 'true':
                return {'enabled': False, 'claimed': 0}
            await poll()
            claimed = claim(int(time.time()))
            await asyncio.gather(*(run_one(j) for j in claimed))
            return {'enabled': True, 'claimed': len(claimed)}
    @app.post('/api/worker/tick')
    async def worker_tick(user=Depends(admin)):
        return await tick()
    @app.post('/api/jobs/{jid}/shop-linked')
    def shop_linked(jid: int, user=Depends(publisher)):
        if not db.query("SELECT 1 FROM jobs WHERE id=? AND status='manual_link'", (jid,)):
            raise HTTPException(409, 'Job is not awaiting a manual Shop link')
        db.execute("UPDATE jobs SET status='success' WHERE id=? AND status='manual_link'", (jid,))
        return {'ok': True}
    app.state.tick = tick
    app.state.claim = claim
    app.state.expire_processing = expire_processing
    from .operations import install as operations
    operations(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event)
