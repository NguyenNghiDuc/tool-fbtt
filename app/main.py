import asyncio
import json
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .db import Database
from .providers import ProviderError, Providers
from .security import check_password, digest, hash_password, random_token, verify_totp


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, max_length=6)


class UserInput(Login):
    password: str = Field(min_length=12, max_length=256)
    role: Literal['admin', 'viewer', 'publisher'] = 'viewer'


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: Literal['facebook', 'tiktok']
    external_id: str | None = Field(default=None, max_length=100, pattern=r'^[\w.-]+$')
    niche: str = Field(default='', max_length=100)
    notes: str = Field(default='', max_length=2000)
    color: str = Field(default='#2563eb', pattern=r'^#[0-9a-fA-F]{6}$')
    status: Literal['active', 'paused', 'error', 'restricted'] = 'paused'


def create_app(settings=None, transport=None, background=True):
    cfg = dict(os.environ) if settings is None else dict(settings)
    cfg.setdefault('DATA_DIR', 'data')
    cfg.setdefault('BASE_URL', 'http://localhost:8000')
    cfg.setdefault('FACEBOOK_API_VERSION', 'v25.0')
    if len(cfg.get('ADMIN_PASSWORD', '')) < 12:
        raise RuntimeError('Set ADMIN_PASSWORD (at least 12 characters)')
    if not cfg.get('ENCRYPTION_KEY'):
        raise RuntimeError('Set ENCRYPTION_KEY; keep it with your database backup')
    cipher = Fernet(cfg['ENCRYPTION_KEY'].encode())
    data_dir = Path(cfg['DATA_DIR'])
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / 'app.sqlite3')
    (data_dir / 'app.sqlite3').chmod(0o600)
    if not db.query('SELECT id FROM users LIMIT 1'):
        db.execute('INSERT INTO users(username,password,role) VALUES (?,?,?)',
                   (cfg.get('ADMIN_USERNAME', 'admin'), hash_password(cfg['ADMIN_PASSWORD']), 'admin'))
    with db.connect() as conn:
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        for name, definition in [('totp_secret', 'TEXT'), ('totp_pending', 'TEXT'), ('totp_pending_expires', 'INTEGER'), ('totp_counter', 'INTEGER DEFAULT -1')]:
            if name not in columns:
                conn.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
    providers = Providers(cfg, transport)

    def event(kind, profile_id, message):
        db.execute('INSERT INTO events(kind,profile_id,message,created) VALUES (?,?,?,?)',
                   (kind, profile_id, message, int(time.time())))

    refresh_lock = asyncio.Lock()

    async def refresh_tokens():
        async with refresh_lock:
            await refresh_tokens_locked()

    async def refresh_tokens_locked():
        for p in db.query("SELECT * FROM profiles WHERE access_token IS NOT NULL"):
            if p['expires'] is None or p['expires'] > time.time() + 86400:
                continue
            previous = p['token_status']
            try:
                if not p['refresh_token']:
                    raise ProviderError('reauthorization_required')
                data = await providers.refresh(p['platform'], cipher.decrypt(p['refresh_token'].encode()).decode())
                refresh = data.get('refresh_token')
                db.execute('UPDATE profiles SET access_token=?,refresh_token=?,expires=?,token_status=? WHERE id=?',
                           (cipher.encrypt(data['access_token'].encode()).decode(),
                            cipher.encrypt(refresh.encode()).decode() if refresh else p['refresh_token'],
                            int(time.time()) + data['expires_in'], 'connected', p['id']))
                event('token_refreshed', p['id'], 'Token refreshed')
            except ProviderError as exc:
                state = 'revoked' if exc.code == 'token_revoked' else 'expiring'
                db.execute('UPDATE profiles SET token_status=? WHERE id=?', (state, p['id']))
                if state != previous:
                    event('token_warning', p['id'], exc.code)
            except (KeyError, TypeError, ValueError):
                db.execute("UPDATE profiles SET token_status='error' WHERE id=?", (p['id'],))
                event('token_warning', p['id'], 'invalid_provider_response')

    async def maintenance():
        refreshed_at = 0
        while True:
            try:
                if time.time() - refreshed_at > 300:
                    await refresh_tokens()
                    refreshed_at = time.time()
                if hasattr(app.state, "scan_inbox"):
                    await app.state.scan_inbox()
                if hasattr(app.state, "tick"):
                    await app.state.tick()
                if hasattr(app.state, "operations_tick"):
                    await app.state.operations_tick()
            except Exception:
                event("maintenance_error", None, "Maintenance failed; retrying next cycle")
            db.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
            db.execute('DELETE FROM oauth_states WHERE expires<?', (int(time.time()),))
            await asyncio.sleep(15)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(maintenance()) if background else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title='FBTT Manager', lifespan=lifespan)
    app.state.db, app.state.cipher, app.state.providers = db, cipher, providers
    app.state.refresh_tokens = refresh_tokens
    app.state.cfg = cfg

    @app.middleware('http')
    async def secure_headers(request, call_next):
        # Require a custom header for browser writes; cross-origin forms cannot set it.
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.headers.get('x-requested-with') != 'FBTT':
            return Response('Missing X-Requested-With: FBTT', status_code=403)
        length = request.headers.get('content-length')
        if length and length.isdigit() and int(length) > 510 * 1024 * 1024:
            return Response('Request too large', status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        return response

    def current_user(request: Request):
        token = request.cookies.get('session', '')
        rows = db.query('SELECT u.id,u.username,u.role FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.hash=? AND s.expires>?',
                        (digest(token), int(time.time())))
        if not rows:
            raise HTTPException(401, 'Login required')
        return rows[0]

    def admin(user=Depends(current_user)):
        if user['role'] != 'admin':
            raise HTTPException(403, 'Admin required')
        return user

    def publisher(user=Depends(current_user)):
        if user['role'] not in ('admin', 'publisher'):
            raise HTTPException(403, 'Publishing permission required')
        return user

    def get_profile(pid):
        rows = db.query('SELECT * FROM profiles WHERE id=?', (pid,))
        if not rows:
            raise HTTPException(404, 'Profile not found')
        return rows[0]

    def public_profile(row):
        return {k: v for k, v in row.items() if k not in ('access_token', 'refresh_token')}

    attempts = {}

    @app.post('/api/login')
    def login(body: Login, request: Request, response: Response):
        key = request.client.host if request.client else 'local'
        now = time.time()
        failures = [t for t in attempts.get(key, []) if now - t < 300]
        attempts[key] = failures
        if len(failures) >= 10:
            raise HTTPException(429, 'Try again in 5 minutes')
        rows = db.query('SELECT * FROM users WHERE username=?', (body.username,))
        if not rows or not check_password(body.password, rows[0]['password']):
            failures.append(now)
            raise HTTPException(401, 'Invalid credentials')
        if rows[0]['totp_secret']:
            secret = cipher.decrypt(rows[0]['totp_secret'].encode()).decode()
            counter = verify_totp(secret, body.otp, rows[0]['totp_counter'])
            if counter is None:
                failures.append(now)
                raise HTTPException(401, 'Invalid credentials or 2FA code')
            with db.connect() as conn:
                changed = conn.execute('UPDATE users SET totp_counter=? WHERE id=? AND totp_counter<?',
                    (counter, rows[0]['id'], counter)).rowcount
            if not changed:
                failures.append(now)
                raise HTTPException(401, '2FA code already used')
        attempts.pop(key, None)
        token = random_token()
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), rows[0]['id'], int(now) + 28800))
        response.set_cookie('session', token, httponly=True, secure=cfg['BASE_URL'].startswith('https://'),
                            samesite='lax', max_age=28800)
        return {'role': rows[0]['role']}

    @app.post('/api/logout')
    def logout(request: Request, response: Response):
        db.execute('DELETE FROM sessions WHERE hash=?', (digest(request.cookies.get('session', '')),))
        response.delete_cookie('session')
        return {'ok': True}

    class PasswordConfirm(BaseModel):
        password: str = Field(min_length=1, max_length=256)

    class OTPConfirm(BaseModel):
        otp: str = Field(pattern=r'^\d{6}$')

    @app.post('/api/2fa/setup')
    def setup_2fa(body: PasswordConfirm, user=Depends(current_user)):
        import base64
        import secrets
        from urllib.parse import quote
        row = db.query('SELECT * FROM users WHERE id=?', (user['id'],))[0]
        if row['totp_secret']:
            raise HTTPException(409, '2FA already enabled')
        if not check_password(body.password, row['password']):
            raise HTTPException(401, 'Invalid password')
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        db.execute('UPDATE users SET totp_pending=?,totp_pending_expires=? WHERE id=?',
            (cipher.encrypt(secret.encode()).decode(), int(time.time()) + 600, user['id']))
        return {'secret': secret, 'uri': 'otpauth://totp/FBTT:' + quote(user['username']) + '?secret=' + secret + '&issuer=FBTT'}

    @app.post('/api/2fa/enable')
    def enable_2fa(body: OTPConfirm, request: Request, user=Depends(current_user)):
        key = 'otp:' + str(user['id'])
        now = time.time()
        failures = [t for t in attempts.get(key, []) if now - t < 300]
        attempts[key] = failures
        if len(failures) >= 10:
            raise HTTPException(429, 'Try again in 5 minutes')
        row = db.query('SELECT * FROM users WHERE id=?', (user['id'],))[0]
        if not row['totp_pending'] or row['totp_pending_expires'] < time.time():
            raise HTTPException(409, 'Start 2FA setup again')
        counter = verify_totp(cipher.decrypt(row['totp_pending'].encode()).decode(), body.otp)
        if counter is None:
            failures.append(now)
            raise HTTPException(422, 'Invalid code')
        with db.connect() as conn:
            conn.execute('UPDATE users SET totp_secret=totp_pending,totp_pending=NULL,totp_counter=? WHERE id=?', (counter, user['id']))
            conn.execute('DELETE FROM sessions WHERE user_id=? AND hash!=?', (user['id'], digest(request.cookies.get('session', ''))))
        attempts.pop(key, None)
        return {'enabled': True}

    @app.get('/api/me')
    def me(user=Depends(current_user)):
        return user

    @app.post('/api/users', status_code=201)
    def add_user(body: UserInput, user=Depends(admin)):
        try:
            uid = db.execute('INSERT INTO users(username,password,role) VALUES (?,?,?)',
                             (body.username, hash_password(body.password), body.role))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Username already exists')
        return {'id': uid, 'username': body.username, 'role': body.role}

    @app.get('/api/users')
    def users(user=Depends(admin)):
        return db.query('SELECT id,username,role FROM users')

    @app.get('/api/profiles')
    def profiles(niche: str | None = None, user=Depends(current_user)):
        rows = db.query('SELECT * FROM profiles ORDER BY id') if niche is None else db.query(
            'SELECT * FROM profiles WHERE niche=? ORDER BY id', (niche,))
        return [public_profile(r) for r in rows]

    @app.post('/api/profiles', status_code=201)
    def add_profile(body: ProfileInput, user=Depends(admin)):
        if body.platform == 'facebook' and not body.external_id:
            raise HTTPException(422, 'Facebook Page ID is required')
        try:
            pid = db.execute('INSERT INTO profiles(name,platform,external_id,niche,notes,color,status) VALUES (?,?,?,?,?,?,?)',
                             tuple(body.model_dump().values()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Profile already exists')
        return public_profile(get_profile(pid))

    @app.put('/api/profiles/{pid}')
    def edit_profile(pid: int, body: ProfileInput, user=Depends(admin)):
        old = get_profile(pid)
        if body.platform != old['platform'] or body.external_id != old['external_id']:
            raise HTTPException(409, 'Platform and account identity are immutable; create a new profile')
        db.execute('UPDATE profiles SET name=?,niche=?,notes=?,color=?,status=? WHERE id=?',
                   (body.name, body.niche, body.notes, body.color, body.status, pid))
        return public_profile(get_profile(pid))

    @app.delete('/api/profiles/{pid}')
    def delete_profile(pid: int, user=Depends(admin)):
        get_profile(pid)
        try:
            db.execute('DELETE FROM profiles WHERE id=?', (pid,))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Profile has publishing history; pause it instead') from None
        return {'ok': True}

    @app.post('/api/profiles/{pid}/oauth')
    def start_oauth(pid: int, user=Depends(admin)):
        p = get_profile(pid)
        state, verifier = random_token(), random_token()
        try:
            url = providers.authorize_url(p['platform'], state, verifier)
        except ProviderError as exc:
            raise HTTPException(503, exc.code)
        db.execute('INSERT INTO oauth_states VALUES (?,?,?,?,?)',
                   (digest(state), user['id'], pid, cipher.encrypt(verifier.encode()).decode(), int(time.time()) + 600))
        return {'url': url}

    @app.get('/oauth/{platform}/callback')
    async def callback(platform: Literal['facebook', 'tiktok'], state: str, code: str | None = None,
                       error: str | None = None, user=Depends(admin)):
        with db.connect() as conn:
            row = conn.execute('DELETE FROM oauth_states WHERE hash=? AND user_id=? AND expires>? RETURNING *',
                               (digest(state), user['id'], int(time.time()))).fetchone()
        if not row:
            raise HTTPException(400, 'Invalid or expired OAuth state')
        p = get_profile(row['profile_id'])
        if p['platform'] != platform or error or not code:
            raise HTTPException(400, 'OAuth denied or invalid callback')
        try:
            tokens = await providers.exchange(platform, code, cipher.decrypt(row['verifier'].encode()).decode(), p['external_id'])
            expiry = int(time.time()) + tokens['expires_in'] if tokens.get('expires_in') else None
            refresh = tokens.get('refresh_token')
            if p['external_id'] and p['external_id'] != tokens['external_id']:
                raise ProviderError('account_mismatch')
            db.execute('UPDATE profiles SET external_id=?,access_token=?,refresh_token=?,expires=?,token_status=? WHERE id=?',
                       (tokens['external_id'], cipher.encrypt(tokens['access_token'].encode()).decode(),
                        cipher.encrypt(refresh.encode()).decode() if refresh else None, expiry, 'connected', p['id']))
        except ProviderError as exc:
            event('oauth_error', p['id'], exc.code)
            raise HTTPException(502, exc.code)
        except (KeyError, TypeError, ValueError, sqlite3.IntegrityError):
            raise HTTPException(502, 'Invalid provider response or duplicate account') from None
        event('oauth_connected', p['id'], 'Account authorized')
        return RedirectResponse('/?connected=1', status_code=303)

    @app.post('/api/tokens/refresh')
    async def refresh(user=Depends(admin)):
        await refresh_tokens()
        return {'ok': True}

    @app.get('/api/events')
    def events(user=Depends(current_user)):
        return db.query('SELECT * FROM events ORDER BY id DESC LIMIT 200')

    @app.get('/health')
    def health():
        db.query('SELECT 1')
        return {'ok': True}

    from .workspace import install
    install(app, db, cfg, current_user, admin, publisher, get_profile, event)
    return app
