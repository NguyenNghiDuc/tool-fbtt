import asyncio
import hashlib
import json
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

class Assignment(BaseModel):
    profile_ids: list[int] = Field(min_length=1, max_length=100)

def probe(path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=30, check=True)
        info = json.loads(result.stdout)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        duration = float(info['format']['duration'])
        if duration <= 0 or duration > 3600:
            raise ValueError()
        return {'width': video['width'], 'height': video['height'], 'duration': duration,
                'vertical': abs(video['width'] / video['height'] - 9 / 16) < 0.03}
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration, OSError):
        raise HTTPException(422, 'Invalid video; ffprobe required; duration must be 0–3600s') from None

def install(app, db, cfg, current_user, admin, publisher, get_profile, event):
    media_dir = Path(cfg['DATA_DIR']) / 'videos'
    media_dir.mkdir(exist_ok=True)
    with db.connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS media (id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
            hash TEXT UNIQUE NOT NULL, metadata TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS assignments (
            media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
            profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            used INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(media_id,profile_id));
        CREATE TABLE IF NOT EXISTS media_products (
            media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
            PRIMARY KEY(media_id,product_id));
        ''')
    def get_media(mid):
        rows = db.query('SELECT * FROM media WHERE id=?', (mid,))
        if not rows:
            raise HTTPException(404, 'Video not found')
        return rows[0]
    def public_media(row):
        return {'id': row['id'], 'name': row['name'], 'created': row['created'], **json.loads(row['metadata']),
                'assignments': db.query('SELECT profile_id,used FROM assignments WHERE media_id=?', (row['id'],))}
    async def ingest(upload):
        suffix = Path(upload.filename or '').suffix.lower()
        if suffix not in ('.mp4', '.mov', '.webm'):
            await upload.close()
            raise HTTPException(422, 'Only mp4, mov and webm supported')
        path = media_dir / (secrets.token_hex(16) + suffix)
        digest, size = hashlib.sha256(), 0
        try:
            with path.open('wb') as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > 500 * 1024 * 1024:
                        raise HTTPException(413, 'Maximum 500 MiB')
                    digest.update(chunk)
                    output.write(chunk)
            meta = await asyncio.to_thread(probe, path)
            meta['size'] = size
            try:
                mid = db.execute('INSERT INTO media(name,path,hash,metadata,created) VALUES (?,?,?,?,?)',
                    (Path(upload.filename).name, str(path), digest.hexdigest(), json.dumps(meta), int(time.time())))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Duplicate video (SHA-256)')
            return public_media(get_media(mid))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
    @app.post('/api/media', status_code=201)
    async def upload_media(file: UploadFile = File(...), user=Depends(admin)):
        return await ingest(file)
    @app.get('/api/media')
    def list_media(user=Depends(current_user)):
        return [public_media(r) for r in db.query('SELECT * FROM media ORDER BY id DESC')]
    @app.get('/api/media/{mid}/video')
    def video(mid: int, user=Depends(current_user)):
        m = get_media(mid)
        return FileResponse(m['path'], filename=m['name'])
    @app.post('/api/media/{mid}/assign')
    def assign(mid: int, body: Assignment, user=Depends(admin)):
        get_media(mid)
        for pid in body.profile_ids:
            get_profile(pid)
        existing = db.query('SELECT profile_id FROM assignments WHERE media_id=?', (mid,))
        with db.connect() as conn:
            for pid in body.profile_ids:
                conn.execute('INSERT OR IGNORE INTO assignments(media_id,profile_id) VALUES (?,?)', (mid, pid))
        return {'ok': True, 'duplicate_warning': len(set(body.profile_ids + [r['profile_id'] for r in existing])) > 1}
    @app.post('/api/media/scan')
    async def scan(user=Depends(admin)):
        watch = Path(cfg['DATA_DIR']) / 'inbox'
        watch.mkdir(exist_ok=True)
        results = []
        for path in sorted(watch.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ('.mp4', '.mov', '.webm'):
                continue
            try:
                result = await ingest(UploadFile(filename=path.name, file=path.open('rb')))
                path.unlink()
                results.append({'file': path.name, 'id': result['id']})
            except HTTPException as exc:
                results.append({'file': path.name, 'error': exc.detail})
        return results
    app.state.scan_inbox = scan
    @app.post('/api/media/{mid}/thumbnail')
    async def thumbnail(mid: int, user=Depends(admin)):
        m = get_media(mid)
        destination = media_dir / f'{mid}.jpg'
        try:
            await asyncio.to_thread(subprocess.run, ['ffmpeg', '-v', 'error', '-y', '-i', m['path'],
                '-frames:v', '1', '-vf', 'scale=360:-2', str(destination)], capture_output=True, timeout=30, check=True)
        except (subprocess.SubprocessError, OSError):
            raise HTTPException(422, 'Could not generate thumbnail') from None
        return {'url': f'/api/media/{mid}/thumbnail'}
    @app.get('/api/media/{mid}/thumbnail')
    def get_thumbnail(mid: int, user=Depends(current_user)):
        get_media(mid)
        path = media_dir / f'{mid}.jpg'
        if not path.exists():
            raise HTTPException(404, 'Generate a thumbnail first')
        return FileResponse(path, media_type='image/jpeg')
    from .commerce import install as commerce
    commerce(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event)
