"""Farcaster via Neynar's hosted API, casting from the user's own account (signer)."""
import os

import httpx

from .base import Channel, ChannelError


class FarcasterChannel(Channel):
    name = "farcaster"
    env_vars = ("NEYNAR_API_KEY", "NEYNAR_SIGNER_UUID")

    async def post(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.neynar.com/v2/farcaster/cast",
                             headers={"x-api-key": os.environ["NEYNAR_API_KEY"]},
                             json={"signer_uuid": os.environ["NEYNAR_SIGNER_UUID"], "text": text})
        if r.status_code >= 300:
            raise ChannelError(f"Farcaster: HTTP {r.status_code} {r.text[:200]}")
        return f"farcaster:{r.json().get('cast', {}).get('hash')}"
