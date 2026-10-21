import json
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, model_validator


class Resolution(BaseModel):
    outcome: Literal['published', 'not_published']
    confirmed: bool = False
    remote_id: str | None = Field(default=None, min_length=1, max_length=200,
                                  pattern=r'^[A-Za-z0-9_.:~\-]+$')

    @model_validator(mode='after')
    def require_remote_id(self):
        if self.outcome == 'published' and not self.remote_id:
            raise ValueError('Enter the post/video ID you verified on the platform')
        return self


def install(app, db, publisher):
    with db.connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS job_resolutions (
            id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
            user_id INTEGER NOT NULL REFERENCES users(id), outcome TEXT NOT NULL,
            previous_remote_id TEXT, remote_id TEXT, previous_error TEXT,
            previous_started INTEGER, attempts INTEGER NOT NULL, created INTEGER NOT NULL
        )''')

    @app.post('/api/jobs/{jid}/resolve')
    def resolve(jid: int, body: Resolution, user=Depends(publisher)):
        if not body.confirmed:
            raise HTTPException(422, 'Check the account on the platform and confirm the result first')
        now = int(time.time())
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Job not found')
            job = dict(row)
            if job['status'] != 'uncertain':
                raise HTTPException(409, 'Only uncertain jobs can be reconciled; refresh the queue')
            platform = conn.execute('SELECT platform FROM profiles WHERE id=?', (job['profile_id'],)).fetchone()['platform']
            if body.outcome == 'published':
                status = 'manual_link' if platform == 'tiktok' else 'success'
                conn.execute('''UPDATE jobs SET status=?,remote_id=?,error=NULL,
                    started=COALESCE(started,?),processing_since=NULL WHERE id=?''',
                    (status, body.remote_id, now, jid))
                conn.execute('UPDATE assignments SET used=1 WHERE media_id=? AND profile_id=?',
                             (job['media_id'], job['profile_id']))
            else:
                # Release the profile, but reserve this video behind an explicit new approval.
                # Neither the scheduler nor the worker can re-post it automatically.
                status = 'pending'
                conn.execute('''UPDATE jobs SET status='pending',remote_id=NULL,error=NULL,
                    started=NULL,processing_since=NULL,scheduled=MAX(scheduled,?) WHERE id=?''', (now, jid))
            conn.execute('''INSERT INTO job_resolutions
                (job_id,user_id,outcome,previous_remote_id,remote_id,previous_error,previous_started,attempts,created)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (jid, user['id'], body.outcome, job['remote_id'], body.remote_id,
                 job['error'], job['started'], job['attempts'], now))
            # Audit and transition commit together; user input never goes into error messages.
            conn.execute('INSERT INTO events(kind,profile_id,message,created) VALUES (?,?,?,?)',
                         ('job_resolved', job['profile_id'], json.dumps({
                             'job_id': jid, 'user_id': user['id'], 'outcome': body.outcome,
                             'status': status,
                         }), now))
        return db.query('SELECT * FROM jobs WHERE id=?', (jid,))[0]

    @app.get('/api/jobs/{jid}/resolutions')
    def resolutions(jid: int, user=Depends(publisher)):
        if not db.query('SELECT 1 FROM jobs WHERE id=?', (jid,)):
            raise HTTPException(404, 'Job not found')
        return db.query('''SELECT r.*,u.username FROM job_resolutions r JOIN users u ON u.id=r.user_id
            WHERE job_id=? ORDER BY r.id''', (jid,))
