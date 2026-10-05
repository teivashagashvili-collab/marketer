"""Bluesky via the AT Protocol XRPC API with an app password."""
import os
from datetime import datetime, timezone

import httpx

from .base import Channel, ChannelError

PDS = "https://bsky.social/xrpc"


class BlueskyChannel(Channel):
    name = "bluesky"
    env_vars = ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")

    async def post(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            s = await c.post(f"{PDS}/com.atproto.server.createSession",
                             json={"identifier": os.environ["BLUESKY_HANDLE"],
                                   "password": os.environ["BLUESKY_APP_PASSWORD"]})
            if s.status_code != 200:
                raise ChannelError(f"Bluesky login: HTTP {s.status_code}")
            sess = s.json()
            record = {"$type": "app.bsky.feed.post", "text": text,
                      "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            r = await c.post(f"{PDS}/com.atproto.repo.createRecord",
                             headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                             json={"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record})
        if r.status_code != 200:
            raise ChannelError(f"Bluesky: HTTP {r.status_code} {r.text[:200]}")
        rkey = r.json()["uri"].rsplit("/", 1)[-1]
        return f"https://bsky.app/profile/{sess['handle']}/post/{rkey}"
