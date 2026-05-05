from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..config import CONFIG_PATH, DATA_DIR, PORT, SESSION_COOKIE_NAME, SETTINGS, WEB_ROOT_DIR
from ..security import require_page_login, sanitize_next_url
from ..state import completed_uploads, upload_tracker
from ..ui import render_app_page, render_home_page, render_login_page
from ..utils import auth_configured, create_session_token, verify_password

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root_page():
    return render_home_page()


@router.get("/login", response_class=HTMLResponse)
async def login_page(next: Optional[str] = None):
    return render_login_page(sanitize_next_url(next))


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
):
    desired_next = sanitize_next_url(next)
    user = SETTINGS["users"].get(username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        return HTMLResponse(render_login_page(desired_next, "Invalid username or password."), status_code=401)

    response = RedirectResponse(url=desired_next, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user["username"]),
        max_age=SETTINGS["session_max_age_seconds"],
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.get("/logout")
async def logout_page():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/home")
async def home_redirect():
    return RedirectResponse(url="/app", status_code=303)


@router.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return render_app_page(username)


@router.get("/clipboard")
async def clipboard_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@router.get("/upload")
async def upload_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@router.get("/chunked-upload")
async def chunked_upload_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@router.get("/status")
async def global_status(request: Request):
    username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return JSONResponse({
        "port": PORT,
        "config_path": str(CONFIG_PATH),
        "data_dir": str(DATA_DIR),
        "web_root": str(WEB_ROOT_DIR),
        "current_user": username,
        "tracked_api_uploads": len(upload_tracker),
        "completed_api_uploads": len(completed_uploads),
        "auth_configured": auth_configured(),
        "web_file_retention_days": SETTINGS["web_file_retention_days"],
    })


@router.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{request.app.title} - Docs")


@router.get("/openapi.json")
async def openapi_json(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    schema = get_openapi(
        title=request.app.title,
        version=request.app.version,
        routes=request.app.routes,
        description=request.app.description,
    )
    return JSONResponse(schema)


@router.get("/docs/oauth2-redirect", response_class=HTMLResponse)
async def swagger_oauth2_redirect(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return get_swagger_ui_oauth2_redirect_html()
