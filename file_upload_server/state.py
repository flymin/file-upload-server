import asyncio
from typing import Dict

# Legacy API upload state, kept for interface compatibility.
upload_tracker: Dict[str, dict] = {}
completed_uploads: Dict[str, dict] = {}

# Web upload concurrency guards.
web_upload_locks: Dict[str, asyncio.Lock] = {}
user_state_locks: Dict[str, asyncio.Lock] = {}


def get_user_state_lock(username: str) -> asyncio.Lock:
    if username not in user_state_locks:
        user_state_locks[username] = asyncio.Lock()
    return user_state_locks[username]


def get_web_upload_lock(upload_id: str) -> asyncio.Lock:
    if upload_id not in web_upload_locks:
        web_upload_locks[upload_id] = asyncio.Lock()
    return web_upload_locks[upload_id]
