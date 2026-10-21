"""Create local secrets once; never overwrite or print credentials."""
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
example = (root / '.env.example').read_text()
example = example.replace('replace-with-a-long-password', secrets.token_urlsafe(24))
example = example.replace('generate-a-fernet-key', Fernet.generate_key().decode())
path = root / '.env'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(example)
(root / 'data').mkdir(mode=0o700, exist_ok=True)
print('Created .env (mode 600). View ADMIN_PASSWORD locally; keep ENCRYPTION_KEY in a secure backup.')
