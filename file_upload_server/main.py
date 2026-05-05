import uvicorn
from fastapi import FastAPI

from .config import API_CHUNKS_DIR, CONFIG_PATH, DATA_DIR, PORT, SETTINGS, TOKEN_HEADER_NAME, UPLOAD_TOKEN, WEB_ROOT_DIR
from .exceptions import SilentReject, silent_reject_handler
from .routes import api, pages, web_clipboard, web_files


def create_app() -> FastAPI:
    app = FastAPI(
        title="File Upload Server",
        description="Stable token upload API plus multi-user web workspace.",
        version="3.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_exception_handler(SilentReject, silent_reject_handler)
    app.include_router(pages.router)
    app.include_router(web_clipboard.router)
    app.include_router(web_files.router)
    app.include_router(api.router)
    return app


app = create_app()


def run() -> None:
    print(f"Port           : {PORT}")
    print(f"Config         : {CONFIG_PATH}")
    print(f"Data dir       : {DATA_DIR}")
    print(f"API chunk dir  : {API_CHUNKS_DIR}")
    print(f"Web root dir   : {WEB_ROOT_DIR}")
    print(f"Docs           : http://localhost:{PORT}/docs")
    print(f"Token header   : {TOKEN_HEADER_NAME}")
    print(f"API auth       : {'enabled' if UPLOAD_TOKEN else 'disabled'}")
    print(f"Web users      : {', '.join(sorted(SETTINGS['users'].keys()))}")
    print(f"File retention : {SETTINGS['web_file_retention_days']} day(s)")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
