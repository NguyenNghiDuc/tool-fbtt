import tempfile
import uvicorn
from cryptography.fernet import Fernet
from app.main import create_app

with tempfile.TemporaryDirectory() as directory:
    app = create_app({'DATA_DIR':directory,'ADMIN_PASSWORD':'browser-test-password','ENCRYPTION_KEY':Fernet.generate_key().decode()},background=False)
    uvicorn.run(app, host='127.0.0.1', port=8765, access_log=False)
