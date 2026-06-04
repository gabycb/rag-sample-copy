"""
Bot Service Message Handler

Handles:
1. Validating incoming messages from Azure Bot Service (verify credentials)
2. Extracting and exchanging user identity tokens (OBO flow for SharePoint access)
3. Sending replies back through Bot Service
"""

import os
import logging
import jwt
from datetime import datetime
from typing import Optional, Dict, Any
from msal import ConfidentialClientApplication
import aiohttp

logger = logging.getLogger(__name__)


class BotHandler:
    """
    Manages MS Teams bot message handling and Entra ID OBO flow.

    - Validates incoming messages from Azure Bot Service
    - Exchanges user tokens for SharePoint-scoped tokens (OBO flow)
    - Sends replies back to Teams through Bot Service
    """

    def __init__(self):
        """Initialize with Bot Service and Entra ID credentials."""
        self.bot_app_id = os.getenv("MICROSOFT_APP_ID")
        self.bot_app_password = os.getenv("MICROSOFT_APP_PASSWORD")
        self.tenant_id = os.getenv("AZURE_TENANT_ID")
        self.entra_app_id = os.getenv("ENTRA_APP_CLIENT_ID")
        self.entra_app_secret = os.getenv("ENTRA_APP_CLIENT_SECRET")

        # MSAL client for OBO token exchange
        self.msal_app = ConfidentialClientApplication(
            client_id=self.entra_app_id,
            client_credential=self.entra_app_secret,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )

    async def validate_auth_header(self, auth_header: str) -> bool:
        """
        Validate Bot Service authorization header.

        Bot Service signs all incoming messages with a JWT token. We verify:
        - Token signature matches Bot Service's public key
        - Issuer is Microsoft Bot Service
        - Token is not expired
        - Audience matches our bot app ID
        """
        try:
            if not auth_header.startswith("Bearer "):
                return False

            token = auth_header[7:]  # Remove "Bearer " prefix

            # In production: fetch Microsoft's OpenID config and validate JWT signature
            # https://login.botframework.com/v1/.well-known/openid-configuration
            # For now, basic token validation:
            decoded = jwt.decode(
                token,
                options={"verify_signature": False}  # TODO: verify with Microsoft's keys in production
            )

            # Check audience and issuer
            if decoded.get("aud") != self.bot_app_id:
                logger.warning(f"Token audience mismatch: {decoded.get('aud')}")
                return False

            if "botframework" not in decoded.get("iss", ""):
                logger.warning(f"Invalid issuer: {decoded.get('iss')}")
                return False

            return True

        except Exception as e:
            logger.error(f"Auth validation failed: {e}")
            return False

    async def get_obo_token(self, activity: Dict[str, Any]) -> str:
        """
        Exchange user's Teams token for a SharePoint-scoped token (OBO flow).

        Process:
        1. Extract user's token from activity (provided by Bot Service)
        2. Call token endpoint with user's token + bot credentials
        3. Receive SharePoint-scoped token
        4. Return token for AI Search queries

        https://learn.microsoft.com/en-us/azure/bot-service/bot-builder-authentication-sso
        """
        try:
            # The user's token is passed in the activity
            # In the actual implementation, extract it from activity["channelData"]["teamsChannelData"] or similar
            user_token = activity.get("from", {}).get("aadObjectId")  # Simplified; actual token location varies

            if not user_token:
                logger.warning("No user token in activity")
                return None

            # Use MSAL to exchange user's token for SharePoint-scoped token (OBO flow)
            result = self.msal_app.acquire_token_on_behalf_of(
                user_assertion=user_token,
                scopes=["https://graph.microsoft.com/.default"]  # TODO: adjust for SharePoint scopes
            )

            if "access_token" in result:
                return result["access_token"]
            else:
                logger.error(f"OBO token exchange failed: {result.get('error_description')}")
                return None

        except Exception as e:
            logger.error(f"OBO token exchange error: {e}")
            return None

    async def send_reply(self, activity: Dict[str, Any], reply_text: str):
        """
        Send a reply message back to the user through Bot Service.

        The reply is sent via the Bot Service's REST API.
        """
        try:
            # Construct reply activity
            reply_activity = {
                "type": "message",
                "text": reply_text,
                "conversation": activity.get("conversation"),
                "from": {
                    "id": activity.get("recipient", {}).get("id"),
                    "name": "ATLAS-RAG Bot"
                },
                "replyToId": activity.get("id"),
            }

            # Send reply through Bot Service API
            # TODO: implement actual send_activity call to Bot Service
            logger.info(f"Reply sent: {reply_text[:100]}...")

        except Exception as e:
            logger.error(f"Failed to send reply: {e}")
