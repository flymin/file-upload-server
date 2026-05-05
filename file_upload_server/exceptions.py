from fastapi import Response


class SilentReject(Exception):
    """Best-effort silent reject for unauthorized requests."""


class RangeNotSatisfiable(Exception):
    pass


async def silent_reject_handler(request, exc):
    return Response(status_code=404, content=b"", headers={"Connection": "close"})
