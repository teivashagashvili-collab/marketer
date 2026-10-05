"""X (Twitter) via the official v2 API, posting as the user's own account (OAuth 1.0a).

X's automation rules allow scheduled original posts from your own account. They forbid
automated replies/mentions to people who didn't ask, mass DMs, trend spam and running
multiple accounts for the same content, so this adapter only creates original posts.
Posting needs a paid API tier with write access.
"""
import asyncio
import os

import tweepy

from .base import Channel, ChannelError


class XChannel(Channel):
    name = "x"
    env_vars = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")

    def _client(self) -> tweepy.Client:
        return tweepy.Client(
            consumer_key=os.environ["X_API_KEY"],
            consumer_secret=os.environ["X_API_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_SECRET"],
        )

    async def post(self, text: str) -> str:
        try:
            resp = await asyncio.to_thread(self._client().create_tweet, text=text)
        except tweepy.TweepyException as e:
            raise ChannelError(f"X: {e}") from e
        return f"https://x.com/i/web/status/{resp.data['id']}"
