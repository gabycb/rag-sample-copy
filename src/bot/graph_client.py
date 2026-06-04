"""
Microsoft Graph client — resolves the *caller's* identity set for security trimming.

Given a Graph access token (obtained via the OBO exchange for the signed-in user),
returns the user's object id plus the full set of Entra group object ids they belong
to (transitive). PR3's AI Search filter uses this set so a user only ever sees
documents whose ACL (`allowedGroups` / `allowedUsers`) intersects their identity.

In `APP_MODE=local` this returns deterministic fakes from an in-memory directory so
per-user trimming can be demonstrated and unit-tested without a tenant.
"""

import logging
import time
from dataclasses import dataclass, field

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CallerIdentity:
    """The signed-in user's identity, as used for security trimming."""

    oid: str
    group_ids: list[str] = field(default_factory=list)
    upn: str | None = None

    @property
    def principal_ids(self) -> list[str]:
        """All principal ids that may appear in a document ACL (user + groups)."""
        return [self.oid, *self.group_ids]


# In-memory directory used only when APP_MODE=local. Lets tests prove that user A
# and user B resolve to different groups (and therefore see different documents).
LOCAL_DIRECTORY: dict[str, CallerIdentity] = {
    "alice": CallerIdentity(
        oid="00000000-0000-0000-0000-0000000a11ce",
        upn="alice@contoso.com",
        group_ids=["grp-engineering", "grp-allstaff"],
    ),
    "bob": CallerIdentity(
        oid="00000000-0000-0000-0000-000000000b0b",
        upn="bob@contoso.com",
        group_ids=["grp-sales", "grp-allstaff"],
    ),
}


class GraphClient:
    """Resolves caller identity + transitive group membership from Microsoft Graph."""

    def __init__(self, *, cache_ttl_seconds: int = 300) -> None:
        self._settings = get_settings()
        self._cache_ttl = cache_ttl_seconds
        # token -> (expiry_epoch, CallerIdentity)
        self._cache: dict[str, tuple[float, CallerIdentity]] = {}

    async def get_caller_identity(self, graph_token: str) -> CallerIdentity:
        """Resolve the caller's identity, caching per token for a short TTL."""
        cached = self._cache.get(graph_token)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        identity = await self._resolve(graph_token)
        self._cache[graph_token] = (time.monotonic() + self._cache_ttl, identity)
        return identity

    async def _resolve(self, graph_token: str) -> CallerIdentity:
        if self._settings.is_local:
            return self._resolve_local(graph_token)

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {graph_token}"}
            me = await client.get(
                f"{self._settings.graph_base_url}/me?$select=id,userPrincipalName",
                headers=headers,
            )
            me.raise_for_status()
            me_json = me.json()
            oid = me_json["id"]
            upn = me_json.get("userPrincipalName")

            group_ids = await self._fetch_transitive_groups(client, headers)

        logger.info("Resolved caller %s with %d transitive groups", oid, len(group_ids))
        return CallerIdentity(oid=oid, group_ids=group_ids, upn=upn)

    async def _fetch_transitive_groups(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> list[str]:
        """Page through /me/transitiveMemberOf, collecting group object ids."""
        url: str | None = (
            f"{self._settings.graph_base_url}/me/transitiveMemberOf/microsoft.graph.group"
            "?$select=id&$top=999"
        )
        group_ids: list[str] = []
        while url:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            group_ids.extend(item["id"] for item in payload.get("value", []) if "id" in item)
            url = payload.get("@odata.nextLink")
        return group_ids

    def _resolve_local(self, graph_token: str) -> CallerIdentity:
        """Deterministic fake resolution keyed by the (fake) token string."""
        key = graph_token.removeprefix("local-graph-token:")
        if key in LOCAL_DIRECTORY:
            return LOCAL_DIRECTORY[key]
        # Unknown user: minimal membership so trimming still applies.
        return CallerIdentity(oid=key or "local-user", group_ids=["grp-allstaff"])
