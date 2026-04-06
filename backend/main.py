from fastapi import FastAPI

from api.webhook import router as webhook_router

app = FastAPI(title="MailMind Backend")
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
