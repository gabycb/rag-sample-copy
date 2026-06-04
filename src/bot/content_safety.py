"""
Input guard — Azure AI Content Safety **Prompt Shields**.

Runs before retrieval/generation to block user prompt-injection / jailbreak attempts.
Because retrieved SharePoint content is attacker-influenceable, indirect prompt
injection is a first-class risk for this system; this is the runtime mitigation, and
the offline IndirectAttack evaluator (see eval/) is the regression gate.

Gated by `ENABLE_CONTENT_SAFETY=true`. In `APP_MODE=local` a deterministic heuristic
stands in for the service so the integration is testable offline.
"""

import logging
from dataclasses import dataclass, field

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
_SHIELD_API_VERSION = "2024-09-01"

# Heuristic markers used only by the local fake.
_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "disregard the above",
    "disregard previous",
    "forget your instructions",
    "reveal your instructions",
    "reveal your system prompt",
    "print your system prompt",
    "you are now",
    "do anything now",
    "act as dan",
    "override your",
    "bypass your",
)


@dataclass
class ShieldResult:
    blocked: bool = False
    reason: str = ""
    categories: list[str] = field(default_factory=list)


class ContentSafetyGuard:
    """Prompt-injection / jailbreak shield for user input (and retrieved documents)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.enable_content_safety

    async def check_input(
        self, user_prompt: str, documents: list[str] | None = None
    ) -> ShieldResult:
        if not self.enabled:
            return ShieldResult(blocked=False)
        if self.settings.is_local:
            return self._check_local(user_prompt, documents or [])
        return await self._check_azure(user_prompt, documents or [])

    # ----------------------------------------------------------------- local
    def _check_local(self, user_prompt: str, documents: list[str]) -> ShieldResult:
        haystacks = [user_prompt, *documents]
        for text in haystacks:
            lowered = text.lower()
            for marker in _INJECTION_MARKERS:
                if marker in lowered:
                    return ShieldResult(
                        blocked=True,
                        reason=f"prompt-injection pattern: '{marker}'",
                        categories=["JailbreakAttack"],
                    )
        return ShieldResult(blocked=False)

    # ----------------------------------------------------------------- azure
    async def _check_azure(self, user_prompt: str, documents: list[str]) -> ShieldResult:
        from azure.identity.aio import DefaultAzureCredential

        endpoint = self.settings.content_safety_endpoint
        if not endpoint:
            logger.warning("Content safety enabled but AZURE_CONTENT_SAFETY_ENDPOINT unset")
            return ShieldResult(blocked=False)

        credential = DefaultAzureCredential(
            managed_identity_client_id=self.settings.managed_identity_client_id
        )
        token = (await credential.get_token(_COGNITIVE_SCOPE)).token
        await credential.close()

        url = f"{endpoint.rstrip('/')}/contentsafety/text:shieldPrompt?api-version={_SHIELD_API_VERSION}"
        body = {"userPrompt": user_prompt, "documents": documents}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url, json=body, headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("userPromptAnalysis", {}).get("attackDetected"):
            return ShieldResult(True, "user prompt attack detected", ["UserPromptAttack"])
        for doc in data.get("documentsAnalysis", []):
            if doc.get("attackDetected"):
                return ShieldResult(True, "indirect attack in document", ["IndirectAttack"])
        return ShieldResult(blocked=False)
