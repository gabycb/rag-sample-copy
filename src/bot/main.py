"""
ATLAS-RAG Bot Service

FastAPI server that handles MS Teams messages via Azure Bot Service webhook.
Routes messages to AI Foundry agent for RAG-based Q&A over SharePoint content.

Message Flow:
  1. User sends question in MS Teams
  2. Teams → Azure Bot Service → /api/messages webhook (this server)
  3. bot_handler.py validates Bot Service credentials + extracts user token
  4. ai_foundry_client.py invokes AI Foundry agent with OBO token
  5. Agent retrieves docs from AI Search (scoped to user permissions)
  6. Agent sends answer back → Bot Service → Teams
"""

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import logging
import os
from dotenv import load_dotenv

from bot_handler import BotHandler
from ai_foundry_client import AIFoundryClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="ATLAS-RAG Bot Service")

# Initialize bot handler and AI Foundry client
bot_handler = BotHandler()
ai_client = AIFoundryClient()


@app.get("/health")
async def health():
    """Liveness probe — the process is up."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """
    Readiness probe — the app has constructed its handler/clients and can serve traffic.

    Kept separate from /health so an unready (still-initializing or mis-configured)
    instance is taken out of rotation without being killed by the liveness probe.
    """
    initialized = bot_handler is not None and ai_client is not None
    if not initialized:
        return JSONResponse(status_code=503, content={"status": "not-ready"})
    return {"status": "ready"}


@app.post("/api/messages")
async def handle_messages(request: Request):
    """
    Bot Service webhook endpoint.

    Receives activity objects from Azure Bot Service (Teams messages, conversational updates, etc.)
    Validates credentials, extracts user context, routes to AI agent.
    """
    body = await request.json()

    try:
        # Validate Bot Service credentials
        auth_header = request.headers.get("Authorization", "")
        is_valid = await bot_handler.validate_auth_header(auth_header)
        if not is_valid:
            logger.warning("Invalid Bot Service credentials")
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Extract activity and user context
        activity = body
        user_id = activity.get("from", {}).get("id")
        user_name = activity.get("from", {}).get("name")
        conversation_id = activity.get("conversation", {}).get("id")
        message_text = activity.get("text", "").strip()

        if activity.get("type") == "message" and message_text:
            logger.info(f"Message from {user_name} ({user_id}): {message_text}")

            # Get OBO token for this user (for SharePoint access)
            user_token = await bot_handler.get_obo_token(activity)

            # Invoke AI Foundry agent with message + user token
            response_text = await ai_client.query_agent(
                query=message_text,
                user_token=user_token,
                conversation_id=conversation_id,
                user_id=user_id,
            )

            # Send response back through Bot Service
            await bot_handler.send_reply(
                activity=activity,
                reply_text=response_text
            )

        return Response(status_code=200)

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
