"""
Bot Service message handler.

Responsibilities:
1. Authenticate incoming Activities from Azure Bot Service (real Bot Framework
   JWT validation — NOT the previous `verify_signature=False` bypass).
2. Obtain the signed-in user's token (Teams SSO) and exchange it On-Behalf-Of
   (OBO) for a Microsoft Graph token, then resolve the caller's identity +
   transitive groups (see graph_client.py) for security trimming.
3. Run the supplied message pipeline and send the reply back through Bot Service.

`APP_MODE=local` bypasses JWKS validation and uses fake identities so the full
path is runnable/testable offline. All heavyweight SDKs (botbuilder, msal) are
imported lazily inside the Azure path so the local/test path needs only httpx.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from config import get_settings
from graph_client import CallerIdentity, GraphClient

logger = logging.getLogger(__name__)

# Pipeline callback: (query, caller_identity, conversation_id, user_id) -> reply text
MessagePipeline = Callable[[str, CallerIdentity, str, str], Awaitable[str]]

_GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]
_TOKEN_EXCHANGE_INVOKE = "signin/tokenExchange"


@dataclass
class TurnResult:
    """What the HTTP layer should return for a processed activity."""

    status_code: int = 200
    body: dict[str, Any] | None = None


class BotHandler:
    """Validates Bot Service traffic and drives the OBO + identity-resolution flow."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.graph = GraphClient()
        self._msal_app = None
        self._adapter = None

        if not self.settings.is_local:
            self._init_azure_clients()

    # ------------------------------------------------------------------ setup
    def _init_azure_clients(self) -> None:
        """Construct Bot Framework + MSAL clients (Azure mode only)."""
        from botbuilder.core import CloudAdapter, ConfigurationBotFrameworkAuthentication
        from msal import ConfidentialClientApplication

        # Bot Framework auth config — MSI-based, so there is no app password.
        class _BotConfig:
            APP_ID = self.settings.bot_app_id
            APP_TYPE = self.settings.bot_app_type
            APP_TENANTID = self.settings.bot_app_tenant_id
            APP_PASSWORD = ""  # unused with UserAssignedMSI

        self._adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(_BotConfig))
        self._adapter.on_turn_error = self._on_turn_error

        # OBO requires the app's own credential (secret here; a federated managed-identity
        # credential is the secret-less production alternative — see docs).
        if self.settings.obo_client_id and self.settings.obo_client_secret:
            self._msal_app = ConfidentialClientApplication(
                client_id=self.settings.obo_client_id,
                client_credential=self.settings.obo_client_secret,
                authority=f"https://login.microsoftonline.com/{self.settings.tenant_id}",
            )
        else:
            logger.warning("OBO app credentials missing; OBO exchange will be unavailable.")

    async def _on_turn_error(self, turn_context, error: Exception) -> None:
        logger.error("Unhandled turn error: %s", error, exc_info=True)
        await turn_context.send_activity(
            "Sorry, something went wrong handling your message."
        )

    # --------------------------------------------------------------- OBO flow
    async def exchange_obo(self, user_assertion: str, scopes: list[str]) -> str:
        """
        Exchange the user's token for a downstream-scoped token (OBO).

        `user_assertion` MUST be a real JWT access token issued for this API
        (e.g. from a Teams SSO `signin/tokenExchange`), not a directory object id.
        """
        if self.settings.is_local:
            # Fake graph token that encodes the user key for the fake directory.
            return f"local-graph-token:{user_assertion}"

        if self._msal_app is None:
            raise RuntimeError("OBO client not configured")

        # MSAL is synchronous; keep it off the event loop.
        result = await asyncio.to_thread(
            self._msal_app.acquire_token_on_behalf_of,
            user_assertion=user_assertion,
            scopes=scopes,
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"OBO exchange failed: {result.get('error_description', result.get('error'))}"
            )
        return result["access_token"]

    async def resolve_identity(self, user_assertion: str) -> CallerIdentity:
        """OBO-exchange for a Graph token, then resolve caller identity + groups."""
        graph_token = await self.exchange_obo(user_assertion, _GRAPH_SCOPES)
        return await self.graph.get_caller_identity(graph_token)

    # ---------------------------------------------------------- request entry
    async def handle_turn(
        self, body: dict[str, Any], auth_header: str, pipeline: MessagePipeline
    ) -> TurnResult:
        """Authenticate + route a single incoming activity."""
        if self.settings.is_local:
            return await self._handle_local(body, pipeline)
        return await self._handle_azure(body, auth_header, pipeline)

    # ------------------------------------------------------------ local path
    async def _handle_local(
        self, body: dict[str, Any], pipeline: MessagePipeline
    ) -> TurnResult:
        """Offline path: no JWKS validation, fake identities, reply echoed in body."""
        activity_type = body.get("type")
        user = body.get("from", {})
        # The fake "assertion" is just a directory key (e.g. "alice"/"bob").
        assertion = user.get("aadObjectId") or user.get("id") or "alice"

        if activity_type == "invoke" and body.get("name") == _TOKEN_EXCHANGE_INVOKE:
            assertion = body.get("value", {}).get("token", assertion)
            await self.resolve_identity(assertion)  # warms the identity cache
            return TurnResult(status_code=200, body={"status": "tokenExchanged"})

        if activity_type != "message":
            return TurnResult(status_code=200)

        text = (body.get("text") or "").strip()
        if not text:
            return TurnResult(status_code=200)

        identity = await self.resolve_identity(assertion)
        reply = await pipeline(
            text,
            identity,
            body.get("conversation", {}).get("id", "local-convo"),
            user.get("id", "local-user"),
        )
        logger.info("[local] reply to %s: %s", identity.upn or identity.oid, reply[:120])
        return TurnResult(status_code=200, body={"type": "message", "text": reply})

    # ------------------------------------------------------------ azure path
    async def _handle_azure(
        self, body: dict[str, Any], auth_header: str, pipeline: MessagePipeline
    ) -> TurnResult:
        """Validated Bot Framework path: replies are sent via TurnContext."""
        from botbuilder.core import MessageFactory
        from botbuilder.schema import Activity

        activity = Activity().deserialize(body)

        async def logic(turn_context) -> None:
            assertion = await self._get_user_assertion(turn_context)
            if not assertion:
                # No SSO token yet — prompt the user to sign in (starts Teams SSO).
                await self._send_signin_prompt(turn_context)
                return

            identity = await self.resolve_identity(assertion)

            if (turn_context.activity.type or "").lower() != "message":
                return
            text = (turn_context.activity.text or "").strip()
            if not text:
                return

            reply = await pipeline(
                text,
                identity,
                turn_context.activity.conversation.id,
                turn_context.activity.from_property.id,
            )
            await turn_context.send_activity(MessageFactory.text(reply))

        invoke_response = await self._adapter.process_activity(auth_header, activity, logic)
        if invoke_response is not None:
            return TurnResult(status_code=invoke_response.status, body=invoke_response.body)
        return TurnResult(status_code=200)

    async def _get_user_assertion(self, turn_context) -> str | None:
        """
        Obtain the user's exchangeable SSO token.

        Completed Teams SSO arrives as a `signin/tokenExchange` invoke whose
        `value.token` is the user assertion. (A production bot would also try the
        Bot Framework user-token service for an already-cached token here.)
        """
        activity = turn_context.activity
        if (activity.type or "").lower() == "invoke" and activity.name == _TOKEN_EXCHANGE_INVOKE:
            value = activity.value or {}
            return value.get("token") if isinstance(value, dict) else getattr(value, "token", None)
        return None

    async def _send_signin_prompt(self, turn_context) -> None:
        """Minimal sign-in nudge that triggers the Teams SSO exchange."""
        from botbuilder.core import MessageFactory

        await turn_context.send_activity(
            MessageFactory.text(
                "Please sign in so I can search SharePoint content you have access to."
            )
        )
