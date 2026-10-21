"""Smoke-test an isolated image without production credentials or volumes."""
import os
import secrets
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from cryptography.fernet import Fernet

env = dict(os.environ)
for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):
    env.pop(key, None)
name = 'fbtt-smoke-' + secrets.token_hex(4)
command = ['docker','--host=unix:///var/run/docker.sock']
with tempfile.TemporaryDirectory() as directory:
    credentials = Path(directory) / 'test.env'
    credentials.write_text('ADMIN_PASSWORD=' + secrets.token_urlsafe(24) + '\nENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\nPUBLISH_ENABLED=false\n')
    credentials.chmod(0o600)
    try:
        subprocess.run(command + ['run','-d','--name',name,'--env-file',str(credentials),
            '--mount','type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/run/proxy-ca.pem,readonly',
            '-e','SSL_CERT_FILE=/run/proxy-ca.pem','-p','127.0.0.1:18765:8000','fbtt:test'],check=True,env=env,capture_output=True)
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18765/health',timeout=1) as response:
                    assert response.status == 200
                break
            except (OSError, TimeoutError):
                time.sleep(.25)
        else:
            logs = subprocess.run(command + ['logs','--tail','30',name],env=env,capture_output=True,text=True)
            print(logs.stdout + logs.stderr)
            check = subprocess.run(command + ['exec',name,'python','-c',"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).read().decode())"],env=env,capture_output=True,text=True)
            print('Internal health:',check.stdout,check.stderr)
            raise RuntimeError('Container health check failed')
        with urllib.request.urlopen('http://127.0.0.1:18765/',timeout=3) as response:
            assert 'FBTT' in response.read().decode()
        uid = subprocess.check_output(command + ['exec',name,'id','-u'],env=env,text=True).strip()
        assert uid == '10001'
        print('PASS Docker: non-root container, SQLite initialization, /health, dashboard; no live publishing')
    finally:
        subprocess.run(command + ['rm','-f',name],env=env,capture_output=True)
