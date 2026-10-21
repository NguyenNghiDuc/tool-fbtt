import asyncio
import json
import random
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from .compliance import ReviewConfirmation

ACTIVE = "'pending','queued','publishing','processing','uncertain'"

class Schedule(BaseModel):
    profile_id: int
    product_id: int
    caption_id: int
    times: list[str] = Field(min_length=1, max_length=10)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    timezone: str = 'Asia/Ho_Chi_Minh'
    jitter_minutes: int = Field(default=10, ge=0, le=60)
    daily_limit: int = Field(default=2, ge=1, le=10)
    order: Literal['fifo', 'random'] = 'fifo'
    require_approval: bool = True
    enabled: bool = True
    @field_validator('times')
    @classmethod
    def validate_times(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('Duplicate time slots')
        for value in values:
            if len(value) != 5:
                raise ValueError('Use HH:MM')
            datetime.strptime(value, '%H:%M')
        return sorted(values)
    @field_validator('timezone')
    @classmethod
    def validate_zone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError):
            raise ValueError('Unknown timezone') from None
        return value
    @field_validator('weekdays')
    @classmethod
    def validate_days(cls, values):
        if any(v < 0 or v > 6 for v in values):
            raise ValueError('Weekdays must be 0–6 (Monday–Sunday)')
        return sorted(set(values))

class JobInput(BaseModel):
    profile_id: int
    media_id: int
    product_id: int
    caption_id: int
    scheduled: int = Field(gt=0)

class MoveJob(BaseModel):
    scheduled: int = Field(gt=0)

class Pause(BaseModel):
    paused: bool

def install(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event):
    with db.connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY, profile_id INTEGER UNIQUE NOT NULL
            REFERENCES profiles(id) ON DELETE CASCADE, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT OR IGNORE INTO settings VALUES ('paused','false');
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE RESTRICT,
            media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE RESTRICT,
            product_id INTEGER NOT NULL, caption_id INTEGER NOT NULL, caption TEXT NOT NULL,
            scheduled INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            remote_id TEXT, error TEXT, slot TEXT UNIQUE, created INTEGER NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_job_per_video ON jobs(profile_id,media_id) WHERE status IN ('pending','queued','publishing','processing','uncertain');
        CREATE UNIQUE INDEX IF NOT EXISTS one_publisher_per_profile ON jobs(profile_id) WHERE status='publishing';
        ''')
        # A crash during a remote request has an unknown outcome. Never silently re-post it.
        conn.execute("UPDATE jobs SET status='uncertain',error='worker_interrupted_check_platform' WHERE status='publishing'")
    def paused():
        return db.query("SELECT value FROM settings WHERE key='paused'")[0]['value'] == 'true'
    def schedule_for(pid):
        rows = db.query('SELECT body FROM schedules WHERE profile_id=?', (pid,))
        return json.loads(rows[0]['body']) if rows else {'daily_limit': 2, 'timezone': 'Asia/Ho_Chi_Minh'}
    def make_job(body, approval=True, slot=None):
        profile, media = get_profile(body.profile_id), get_media(body.media_id)
        if not db.query('SELECT 1 FROM assignments WHERE profile_id=? AND media_id=? AND used=0', (body.profile_id, body.media_id)):
            raise HTTPException(409, 'Assign an unused video to this profile first')
        if db.query(f'SELECT 1 FROM jobs WHERE profile_id=? AND media_id=? AND status IN ({ACTIVE})', (body.profile_id, body.media_id)):
            raise HTTPException(409, 'Video already reserved in queue')
        if not json.loads(media['metadata'])['vertical']:
            event('media_warning', body.profile_id, 'Video is not 9:16; review before publishing')
        caption = app.state.render_caption(body.product_id, body.profile_id, body.caption_id)['text']
        try:
            jid = db.execute('INSERT INTO jobs(profile_id,media_id,product_id,caption_id,caption,scheduled,status,slot,created) VALUES (?,?,?,?,?,?,?,?,?)',
                (body.profile_id, body.media_id, body.product_id, body.caption_id, caption, body.scheduled,
                 'pending' if approval else 'queued', slot, int(time.time())))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Schedule slot already exists')
        if hasattr(app.state, 'review_job') and app.state.review_job(jid)['requires_acknowledgment']:
            db.execute("UPDATE jobs SET status='pending' WHERE id=?", (jid,))
        return db.query('SELECT * FROM jobs WHERE id=?', (jid,))[0]
    def get_job(jid):
        rows = db.query('SELECT * FROM jobs WHERE id=?', (jid,))
        if not rows:
            raise HTTPException(404, 'Job not found')
        return rows[0]
    @app.get('/api/schedules')
    def schedules(user=Depends(current_user)):
        return [dict(json.loads(r['body']), id=r['id']) for r in db.query('SELECT * FROM schedules')]
    @app.post('/api/schedules', status_code=201)
    def save_schedule(body: Schedule, user=Depends(admin)):
        get_profile(body.profile_id)
        app.state.find_record('product', body.product_id)
        app.state.find_record('caption', body.caption_id)
        db.execute('INSERT INTO schedules(profile_id,body) VALUES (?,?) ON CONFLICT(profile_id) DO UPDATE SET body=excluded.body',
                   (body.profile_id, body.model_dump_json()))
        return body
    @app.get('/api/jobs')
    def jobs(user=Depends(current_user)):
        return db.query('SELECT * FROM jobs ORDER BY scheduled DESC LIMIT 500')
    @app.post('/api/jobs', status_code=201)
    def add_job(body: JobInput, user=Depends(publisher)):
        return make_job(body)
    @app.post('/api/jobs/{jid}/approve')
    def approve(jid: int, body: ReviewConfirmation, user=Depends(publisher)):
        job = get_job(jid)
        if job['status'] != 'pending':
            raise HTTPException(409, 'Only pending jobs can be approved')
        review = app.state.review_job(jid)
        if review['requires_acknowledgment'] and not body.acknowledged:
            raise HTTPException(409, {'message': 'Review warnings before approval', **review})
        db.execute("UPDATE jobs SET status='queued' WHERE id=? AND status='pending'", (jid,))
        return get_job(jid)
    @app.post('/api/jobs/{jid}/cancel')
    def cancel(jid: int, user=Depends(publisher)):
        if get_job(jid)['status'] not in ('pending', 'queued'):
            raise HTTPException(409, 'Cannot cancel a job that has already started')
        db.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('pending','queued')", (jid,))
        return get_job(jid)
    @app.put('/api/jobs/{jid}/time')
    def move(jid: int, body: MoveJob, user=Depends(publisher)):
        if get_job(jid)['status'] not in ('pending', 'queued'):
            raise HTTPException(409, 'Cannot move a job that has already started')
        db.execute("UPDATE jobs SET scheduled=? WHERE id=? AND status IN ('pending','queued')", (body.scheduled, jid))
        return get_job(jid)
    @app.get('/api/system')
    def system(user=Depends(current_user)):
        return {'paused': paused()}
    @app.post('/api/system/pause')
    def pause(body: Pause, user=Depends(admin)):
        db.execute("UPDATE settings SET value=? WHERE key='paused'", (json.dumps(body.paused),))
        event('system', None, 'Publishing paused' if body.paused else 'Publishing resumed')
        return body
    def plan(now=None):
        now = int(time.time()) if now is None else now
        made = []
        if paused():
            return made
        for row in db.query('SELECT * FROM schedules'):
            schedule = json.loads(row['body'])
            p = get_profile(schedule['profile_id'])
            if not schedule['enabled'] or p['status'] != 'active':
                continue
            zone = ZoneInfo(schedule['timezone'])
            local = datetime.fromtimestamp(now, zone)
            if local.weekday() not in schedule['weekdays']:
                continue
            for clock in schedule['times'][:schedule['daily_limit']]:
                slot = f'{row["id"]}:{local.date()}:{clock}'
                if db.query('SELECT 1 FROM jobs WHERE slot=?', (slot,)):
                    continue
                hour, minute = map(int, clock.split(':'))
                base = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if base.timestamp() < now:
                    continue
                videos = db.query(f'''SELECT m.id FROM media m JOIN assignments a ON a.media_id=m.id
                    WHERE a.profile_id=? AND a.used=0 AND NOT EXISTS
                    (SELECT 1 FROM jobs j WHERE j.media_id=m.id AND j.profile_id=a.profile_id AND j.status IN ({ACTIVE})) ORDER BY m.id''', (p['id'],))
                if not videos:
                    if not db.query("SELECT 1 FROM events WHERE kind='empty_library' AND profile_id=? AND created>?", (p['id'], now - 86400)):
                        event('empty_library', p['id'], 'No unused videos; schedule blocked')
                    break
                mid = random.SystemRandom().choice(videos)['id'] if schedule['order'] == 'random' else videos[0]['id']
                when = int(base.timestamp()) + random.SystemRandom().randint(0, schedule['jitter_minutes'] * 60)
                # Separate profiles by at least one minute; do not spill into the next local day.
                while db.query("SELECT 1 FROM jobs WHERE ABS(scheduled-?)<60 AND status IN ('pending','queued')", (when,)):
                    when += 60
                if datetime.fromtimestamp(when, zone).date() != local.date():
                    continue
                try:
                    made.append(make_job(JobInput(profile_id=p['id'], media_id=mid,
                        product_id=schedule['product_id'], caption_id=schedule['caption_id'], scheduled=when),
                        schedule['require_approval'], slot))
                except HTTPException as exc:
                    event('schedule_blocked', p['id'], str(exc.detail))
        return made
    @app.post('/api/schedules/plan')
    def plan_now(user=Depends(admin)):
        return plan()
    from .compliance import install as compliance
    compliance(app, db, current_user)
    app.state.plan = plan
    app.state.paused = paused
    app.state.schedule_for = schedule_for
    from .publishing import install as publishing
    publishing(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event)
