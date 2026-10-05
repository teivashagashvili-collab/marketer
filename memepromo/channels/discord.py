"""Discord via a channel webhook in a server the user admins.

Self-bots (automating a user account) and posting into other people's servers break
Discord's terms, so webhooks are the supported route.
"""
import os

import httpx

from .base import Channel, ChannelError


class DiscordChannel(Channel):
    name = "discord"
    env_vars = ("DISCORD_WEBHOOK_URL",)

    async def post(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(os.environ["DISCORD_WEBHOOK_URL"], params={"wait": "true"},
                             json={"content": text, "allowed_mentions": {"parse": []}})
        if r.status_code >= 300:
            raise ChannelError(f"Discord: HTTP {r.status_code} {r.text[:200]}")
        return f"discord:{r.json().get('id')}"
