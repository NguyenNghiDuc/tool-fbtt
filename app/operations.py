import asyncio
import csv
import io
import json
import secrets
import smtplib
import sqlite3
import tarfile
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
import httpx

class TrackingInput(BaseModel):
    product_id: int
    profile_id: int
    platform: str = Field(pattern='^(shopee|tiktok)$')
    post_id: int | None = None

class OrderInput(BaseModel):
    product_id: int
    profile_id: int
    order_ref: str = Field(min_length=1, max_length=100)
    revenue: float = Field(ge=0, allow_inf_nan=False)
    commission: float = Field(ge=0, allow_inf_nan=False)

def safe_cell(value):
    text = str(value) if value is not None else ''
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text

def install(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event):
    with db.connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS links(code TEXT PRIMARY KEY, product_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL, post_id INTEGER, destination TEXT NOT NULL, clicks INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL, order_ref TEXT UNIQUE NOT NULL, revenue REAL NOT NULL, commission REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,
            event_id INTEGER UNIQUE NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0);
        CREATE TRIGGER IF NOT EXISTS notify_events AFTER INSERT ON events
            WHEN NEW.kind IN ('publish_error','token_warning','oauth_error','empty_library','daily_summary','maintenance_error')
            BEGIN INSERT INTO notifications(event_id,message)
            VALUES (NEW.id, NEW.kind || ' | profile ' || COALESCE(NEW.profile_id,'system') || ' | ' || NEW.message); END;
        ''')
    @app.get('/api/reports/summary')
    def summary(user=Depends(current_user)):
        return {'profiles': db.query('SELECT status,count(*) AS count FROM profiles GROUP BY status'),
                'jobs': db.query('SELECT status,count(*) AS count FROM jobs GROUP BY status'),
                'by_profile': db.query('SELECT p.id,p.name,j.status,count(j.id) AS count FROM profiles p LEFT JOIN jobs j ON p.id=j.profile_id GROUP BY p.id,j.status'),
                'products': db.query('SELECT product_id,count(*) AS orders,sum(revenue) AS revenue,sum(commission) AS commission FROM orders GROUP BY product_id ORDER BY commission DESC'),
                'clicks': db.query('SELECT profile_id,sum(clicks) AS clicks FROM links GROUP BY profile_id'),
                'publisher_enabled': cfg.get('PUBLISH_ENABLED', 'false').lower() == 'true',
                'paused': app.state.paused()}
    @app.get('/api/reports/jobs.csv')
    def export(user=Depends(current_user)):
        rows = db.query('SELECT j.id,p.name,j.status,j.scheduled,j.attempts,j.remote_id,j.error FROM jobs j JOIN profiles p ON p.id=j.profile_id ORDER BY j.id DESC')
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id','profile','status','scheduled_utc_epoch','attempts','remote_id','error'])
        for row in rows:
            writer.writerow([safe_cell(v) for v in row.values()])
        return Response('\ufeff' + output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=jobs.csv'})
    @app.post('/api/links', status_code=201)
    def create_link(body: TrackingInput, user=Depends(admin)):
        p = app.state.find_record('product', body.product_id)
        get_profile(body.profile_id)
        destination = p[body.platform + '_link']
        if not destination:
            raise HTTPException(409, 'No affiliate URL for this platform')
        if body.post_id is not None and not db.query('SELECT 1 FROM jobs WHERE id=? AND profile_id=?', (body.post_id, body.profile_id)):
            raise HTTPException(404, 'Post not found for this profile')
        code = secrets.token_urlsafe(9)
        db.execute('INSERT INTO links(code,product_id,profile_id,post_id,destination) VALUES (?,?,?,?,?)',
            (code, body.product_id, body.profile_id, body.post_id, destination))
        return {'code': code, 'url': cfg['BASE_URL'].rstrip('/') + '/r/' + code}
    @app.get('/r/{code}')
    def redirect(code: str):
        rows = db.query('SELECT * FROM links WHERE code=?', (code,))
        if not rows:
            raise HTTPException(404, 'Link not found')
        try:
            product = app.state.find_record('product', rows[0]['product_id'])
        except HTTPException:
            raise HTTPException(410, 'Product removed')
        if not product['available']:
            raise HTTPException(410, 'Product unavailable')
        db.execute('UPDATE links SET clicks=clicks+1 WHERE code=?', (code,))
        return RedirectResponse(rows[0]['destination'], status_code=302)
    @app.post('/api/orders', status_code=201)
    def add_order(body: OrderInput, user=Depends(admin)):
        app.state.find_record('product', body.product_id)
        get_profile(body.profile_id)
        try:
            oid = db.execute('INSERT INTO orders(product_id,profile_id,order_ref,revenue,commission) VALUES (?,?,?,?,?)',
                (body.product_id, body.profile_id, body.order_ref, body.revenue, body.commission))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Order reference already imported')
        return {'id': oid}
    @app.get('/api/notifications')
    def notifications(user=Depends(admin)):
        return db.query('SELECT * FROM notifications ORDER BY id DESC LIMIT 200')
    async def send_notifications():
        telegram = cfg.get('TELEGRAM_BOT_TOKEN') and cfg.get('TELEGRAM_CHAT_ID')
        email = cfg.get('SMTP_HOST') and cfg.get('ALERT_EMAIL') and cfg.get('SMTP_FROM')
        if not telegram and not email:
            return {'configured': False, 'sent': 0}
        sent = 0
        for n in db.query("SELECT * FROM notifications WHERE status='queued' AND next_attempt<=? ORDER BY id LIMIT 20", (int(time.time()),)):
            attempts = n['attempts'] + 1
            try:
                if telegram:
                    async with httpx.AsyncClient(transport=app.state.providers.transport, timeout=15) as client:
                        response = await client.post('https://api.telegram.org/bot' + cfg['TELEGRAM_BOT_TOKEN'] + '/sendMessage',
                            json={'chat_id': cfg['TELEGRAM_CHAT_ID'], 'text': n['message'][:4000]})
                    response.raise_for_status()
                    if response.json().get('ok') is not True:
                        raise ValueError('Telegram rejected')
                else:
                    def send_email():
                        message = EmailMessage()
                        message['From'], message['To'], message['Subject'] = cfg['SMTP_FROM'], cfg['ALERT_EMAIL'], 'FBTT notification'
                        message.set_content(n['message'])
                        with smtplib.SMTP(cfg['SMTP_HOST'], int(cfg.get('SMTP_PORT', '587')), timeout=15) as smtp:
                            smtp.starttls()
                            if cfg.get('SMTP_USERNAME'):
                                smtp.login(cfg['SMTP_USERNAME'], cfg['SMTP_PASSWORD'])
                            smtp.send_message(message)
                    await asyncio.to_thread(send_email)
                db.execute("UPDATE notifications SET status='sent',attempts=? WHERE id=?", (attempts, n['id']))
                sent += 1
            except Exception:
                db.execute('UPDATE notifications SET status=?,attempts=?,next_attempt=? WHERE id=?',
                    ('failed' if attempts >= 3 else 'queued', attempts, int(time.time()) + 60 * 2 ** attempts, n['id']))
        return {'configured': True, 'sent': sent}
    @app.post('/api/notifications/send')
    async def send_now(user=Depends(admin)):
        return await send_notifications()
    def daily_summary():
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh'))
        key = 'daily_summary:' + str(now.date())
        if now.hour < 23 or db.query('SELECT 1 FROM settings WHERE key=?', (key,)):
            return
        start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        counts = db.query('SELECT status,count(*) AS count FROM jobs WHERE started>=? GROUP BY status', (start,))
        with db.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, 'sent'))
        event('daily_summary', None, json.dumps(counts))
    def backup():
        directory = Path(cfg['DATA_DIR']) / 'backups'
        directory.mkdir(exist_ok=True)
        stamp = str(int(time.time())) + '-' + secrets.token_hex(4)
        snapshot = directory / (stamp + '.sqlite3')
        destination = directory / (stamp + '.tar.gz')
        try:
            with db.connect() as source:
                target = sqlite3.connect(snapshot)
                try:
                    source.backup(target)
                finally:
                    target.close()
            with tarfile.open(destination, 'w:gz') as archive:
                archive.add(snapshot, arcname='app.sqlite3')
                archive.add(Path(cfg['DATA_DIR']) / 'videos', arcname='videos', recursive=True)
            destination.chmod(0o600)
        finally:
            snapshot.unlink(missing_ok=True)
        return destination
    @app.post('/api/backups')
    async def create_backup(user=Depends(admin)):
        destination = await asyncio.to_thread(backup)
        return FileResponse(destination, filename=destination.name, media_type='application/gzip')
    async def operations_tick():
        daily_summary()
        await send_notifications()
        if cfg.get('AUTO_BACKUP', 'false').lower() == 'true':
            date = datetime.now().date().isoformat()
            key = 'backup:' + date
            if not db.query('SELECT 1 FROM settings WHERE key=?', (key,)):
                await asyncio.to_thread(backup)
                db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, 'done'))
    app.state.operations_tick = operations_tick
    from .dashboard import install as dashboard
    dashboard(app)
