import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["stream"])


async def _event_generator(email_id: str | None = None):
    while True:
        payload = {"type": "heartbeat"}
        if email_id:
            payload["email_id"] = email_id
        yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(5)


@router.get("/stream")
async def stream(email_id: str | None = None) -> StreamingResponse:
    return StreamingResponse(
        _event_generator(email_id=email_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
