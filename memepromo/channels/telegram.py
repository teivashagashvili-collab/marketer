"""Telegram Bot API, posting into a channel or group the user owns, with the bot as admin.

Posting into groups you don't run is spam under Telegram's ToS and gets bots banned.
"""
import os

import httpx

from .base import Channel, ChannelError


class TelegramChannel(Channel):
    name = "telegram"
    env_vars = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

    async def post(self, text: str) -> str:
        url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
                                        "disable_web_page_preview": False})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not body.get("ok"):
            raise ChannelError(f"Telegram: {body.get('description') or r.status_code}")
        return f"telegram:{body['result']['chat']['id']}/{body['result']['message_id']}"
