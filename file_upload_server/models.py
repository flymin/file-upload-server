from typing import Optional
from pydantic import BaseModel


class ClipboardPayload(BaseModel):
    text: str


class WebUploadInitPayload(BaseModel):
    filename: str
    size: int
    content_type: Optional[str] = None
    last_modified_ms: Optional[int] = None
