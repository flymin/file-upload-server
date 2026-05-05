from typing import Optional

import secrets
from fastapi import HTTPException, Request, Security
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyHeader

from .config import TOKEN_HEADER_NAME, UPLOAD_TOKEN
from .exceptions import SilentReject
from .utils import get_current_user


api_key_header = APIKeyHeader(name=TOKEN_HEADER_NAME, auto_error=False)


def require_token(token: Optional[str] = Security(api_key_header)) -> str:
    if not UPLOAD_TOKEN:
        return ""
    if not token or not secrets.compare_digest(token, UPLOAD_TOKEN):
        raise SilentReject()
    return token


def sanitize_next_url(next_url: Optional[str]) -> str:
    if not next_url:
        return "/app"
    cleaned = next_url.strip()
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        return "/app"
    return cleaned


def build_login_redirect(request: Request) -> RedirectResponse:
    from urllib.parse import quote

    next_url = quote(str(request.url.path or "/app"), safe="/?=&%")
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


def require_page_login(request: Request):
    username = get_current_user(request)
    if not username:
        return None, build_login_redirect(request)
    return username, None


def require_json_login(request: Request) -> str:
    username = get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Login required")
    return username
