from .ui_script_clipboard import CLIPBOARD_SCRIPT
from .ui_script_common import COMMON_SCRIPT
from .ui_script_files import FILES_SCRIPT
from .ui_script_uploads import UPLOADS_SCRIPT


def render_app_script(username_js: str, parallelism: int) -> str:
    config_script = f"""const CURRENT_USER = {username_js};
const UPLOAD_PARALLELISM = {parallelism};
const AUTO_REFRESH_MS = 15000;
"""
    return "\n".join([
        config_script,
        COMMON_SCRIPT,
        CLIPBOARD_SCRIPT,
        UPLOADS_SCRIPT,
        FILES_SCRIPT,
    ])
