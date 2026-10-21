import tempfile
import time
import uvicorn
from cryptography.fernet import Fernet
from app.main import create_app

with tempfile.TemporaryDirectory() as directory:
    app = create_app({'DATA_DIR':directory,'ADMIN_PASSWORD':'browser-test-password','ENCRYPTION_KEY':Fernet.generate_key().decode()},background=False)
    # Test-only fault injection. This module is excluded from the production Docker image.
    @app.post('/__test/jobs/{jid}/uncertain')
    def uncertain(jid: int):
        app.state.db.execute("UPDATE jobs SET status='uncertain',error='test_timeout',started=? WHERE id=?", (int(time.time()),jid))
        return {'ok': True}
    uvicorn.run(app, host='127.0.0.1', port=8765, access_log=False, proxy_headers=False)
