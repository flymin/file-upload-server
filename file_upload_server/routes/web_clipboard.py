from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..models import ClipboardPayload
from ..security import require_json_login
from ..state import get_user_state_lock
from ..workspace import delete_clipboard_item, load_clipboard_items, upsert_clipboard_item

router = APIRouter()


@router.get("/web/api/clipboard/items")
async def clipboard_items(request: Request):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        items = sorted(load_clipboard_items(username), key=lambda x: x.get("updated_at") or "", reverse=True)
    return JSONResponse(items)


@router.post("/web/api/clipboard/items")
async def clipboard_add(request: Request, payload: ClipboardPayload):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        item = upsert_clipboard_item(username, payload.text)
    return JSONResponse(item)


@router.delete("/web/api/clipboard/items/{item_id}")
async def clipboard_remove(request: Request, item_id: str):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        ok = delete_clipboard_item(username, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Clipboard item not found")
    return JSONResponse({"ok": True, "deleted": True})
