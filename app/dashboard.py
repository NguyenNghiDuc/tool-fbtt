from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

def install(app):
    directory = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=directory), name='static')
    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(directory / 'index.html', media_type='text/html')
