"""
ATLAS-RAG Bot Service — FastAPI entry point.

Message flow:
  1. User sends a question in MS Teams.
  2. Teams -> Azure Bot Service -> POST /api/messages (this server).
  3. bot_handler validates the Bot Framework JWT, completes Teams SSO + OBO, and
     resolves the caller's identity + groups.
  4. ai_foundry_client runs the AI pipeline scoped to that identity (security trimming).
  5. The reply is sent back through Bot Service (or returned in the body in local mode).

`APP_MODE=local` swaps Azure dependencies for fakes so the whole path runs offline.
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_foundry_client import AIFoundryClient
from bot_handler import BotHandler
from config import get_settings

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Construct handler + AI client at startup (not import time, so import never crashes)."""
    settings = get_settings()
    try:
        app.state.bot_handler = BotHandler()
        app.state.ai_client = AIFoundryClient()
        logger.info("Initialized bot in APP_MODE=%s", settings.app_mode)
    except Exception:  # pragma: no cover - defensive: stay alive for /health
        logger.exception("Initialization failed; service will report not-ready")
        app.state.bot_handler = None
        app.state.ai_client = None
    yield


app = FastAPI(title="ATLAS-RAG Bot Service", lifespan=lifespan)


@app.get("/health")
async def health():
    """Liveness probe — the process is up."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness probe — handler + AI client constructed and ready to serve."""
    initialized = getattr(app.state, "bot_handler", None) is not None and getattr(
        app.state, "ai_client", None
    ) is not None
    if not initialized:
        return JSONResponse(status_code=503, content={"status": "not-ready"})
    return {"status": "ready"}


@app.post("/api/messages")
async def handle_messages(request: Request):
    """Bot Service webhook. Auth + identity handled by bot_handler; AI by ai_client."""
    bot_handler: BotHandler | None = getattr(app.state, "bot_handler", None)
    ai_client: AIFoundryClient | None = getattr(app.state, "ai_client", None)
    if bot_handler is None or ai_client is None:
        return JSONResponse(status_code=503, content={"error": "Service not ready"})

    body = await request.json()
    auth_header = request.headers.get("Authorization", "")

    # The pipeline is the AI work, decoupled from Bot Framework specifics so it can
    # be unit-tested directly. It runs only AFTER identity has been resolved.
    async def pipeline(query, caller_identity, conversation_id, user_id) -> str:
        return await ai_client.query_agent(
            query=query,
            caller_identity=caller_identity,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    try:
        result = await bot_handler.handle_turn(body, auth_header, pipeline)
        return JSONResponse(status_code=result.status_code, content=result.body or {})
    except PermissionError:
        # Raised by Bot Framework auth on an invalid/forged token.
        logger.warning("Rejected unauthenticated request to /api/messages")
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    except Exception:
        # Never leak internals to the caller.
        logger.exception("Error handling message")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
