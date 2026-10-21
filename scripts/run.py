import os
import sys
from pathlib import Path
import uvicorn

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
# Deliberately no shell evaluation, interpolation, or execution of .env content.
if (root / '.env').exists():
    for line in (root / '.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())
uvicorn.run('app.main:create_app', factory=True, host='127.0.0.1', port=8000, workers=1,
            access_log=False, proxy_headers=False)
