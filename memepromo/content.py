"""AI copywriter: turns a TokenInfo snapshot into channel-sized posts with Claude.

Compliance rules live in code, not just the prompt: the contract address and
disclaimer (and "#ad" for paid promos) are appended by `finalize`, and posts with
banned claims are dropped, so the model can't talk its way around them.
"""
from __future__ import annotations

import json
import re

import anthropic

from .config import Settings
from .token_data import TokenInfo

CHANNEL_LIMITS = {
    "x": 280,
    "bluesky": 300,
    "farcaster": 320,
    "telegram": 4000,
    "discord": 1900,
    "dryrun": 1000,
}

# Claims that read as financial promises. Posts containing these are discarded.
BANNED = re.compile(
    r"\b(guarantee[sd]?|risk[- ]?free|can'?t lose|100x|1000x|next \d+x|financial freedom|"
    r"get rich|sure thing|moon guaranteed|insider)\b",
    re.IGNORECASE,
)

SYSTEM = """You write social posts for a Solana memecoin community account run by the token's own team.
Voice: playful, meme-literate, short sentences, a few emojis at most.
Hard rules:
- Use only facts from the token data given. Never invent partnerships, listings, holders or numbers.
- No price predictions, no promises of returns, no "100x", no urgency pressure like "last chance".
- Don't impersonate anyone, don't tag or @mention accounts, don't write replies to other people.
- Don't include the contract address or a disclaimer; the system adds both.
- Each post must make sense on its own and differ from the others and from the recent posts listed."""


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "n/a"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:.1f}{unit}"
    return f"${v:,.6g}"


def token_brief(t: TokenInfo) -> str:
    return "\n".join([
        f"Name: {t.name} (${t.symbol})",
        f"Description: {t.description or 'n/a'}",
        f"Launchpad/DEX: {t.launchpad or 'n/a'}; graduated from bonding curve: {t.graduated}",
        f"Market cap: {_fmt_usd(t.market_cap_usd)}; liquidity: {_fmt_usd(t.liquidity_usd)}; 24h volume: {_fmt_usd(t.volume_24h_usd)}",
        f"Price change 1h: {t.price_change_1h_pct}%; 24h: {t.price_change_24h_pct}%",
        f"Website: {t.website or 'n/a'}; X: {t.twitter or 'n/a'}; Telegram: {t.telegram or 'n/a'}",
    ])


def suffix(t: TokenInfo, settings: Settings) -> str:
    parts = [f"CA: {t.address}"]
    if t.chart_url:
        parts.append(t.chart_url)
    tail = settings.disclaimer
    if settings.paid_promo:
        tail = f"#ad {tail}"
    parts.append(tail)
    return "\n".join(parts)


def finalize(body: str, t: TokenInfo, channel: str, settings: Settings) -> str | None:
    """Attach CA + disclaimer, enforce the length limit, drop non-compliant text."""
    body = body.strip()
    if not body or BANNED.search(body):
        return None
    tail = suffix(t, settings)
    limit = CHANNEL_LIMITS.get(channel, 280)
    if channel in ("x", "bluesky", "farcaster"):
        # Chart links eat short limits; keep CA + disclaimer only.
        tail = "\n".join(line for line in tail.split("\n") if not line.startswith("http"))
    room = limit - len(tail) - 2
    if room < 40:
        return None
    if len(body) > room:
        body = body[: room - 1].rsplit(" ", 1)[0] + "…"
    return f"{body}\n\n{tail}"


class Copywriter:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.client = client

    def _client(self) -> anthropic.AsyncAnthropic:
        if self.client is None:
            self.client = anthropic.AsyncAnthropic()
        return self.client

    async def write(self, t: TokenInfo, channels: list[str], occasion: str, recent: list[str]) -> dict[str, str]:
        """Return {channel: final_post_text}. Falls back to templates without an API key."""
        try:
            drafts = await self._ask_claude(t, channels, occasion, recent)
        except (anthropic.AuthenticationError, anthropic.APIConnectionError, TypeError):
            # TypeError: SDK raises it when no credentials are configured at all.
            drafts = {c: template_post(t, occasion) for c in channels}
        out = {}
        for channel in channels:
            final = finalize(drafts.get(channel, ""), t, channel, self.settings)
            if final:
                out[channel] = final
        return out

    async def _ask_claude(self, t: TokenInfo, channels: list[str], occasion: str, recent: list[str]) -> dict[str, str]:
        limits = {c: CHANNEL_LIMITS.get(c, 280) - 120 for c in channels}
        recent_block = "\n---\n".join(recent[-10:]) or "(none yet)"
        prompt = (
            f"Token data:\n{token_brief(t)}\n\n"
            f"Occasion for this post: {occasion}\n\n"
            f"Recent posts (don't repeat these):\n{recent_block}\n\n"
            f"Write one post per channel. Max characters per channel body: {json.dumps(limits)}"
        )
        schema = {
            "type": "object",
            "properties": {
                "posts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "enum": channels},
                            "text": {"type": "string"},
                        },
                        "required": ["channel", "text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["posts"],
            "additionalProperties": False,
        }
        response = await self._client().beta.messages.create(
            model=self.settings.model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return {}
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text) if text else {"posts": []}
        return {p["channel"]: p["text"] for p in data.get("posts", [])}


def template_post(t: TokenInfo, occasion: str) -> str:
    """Offline fallback so dry runs work without an API key."""
    name = f"${t.symbol}" if t.symbol else (t.name or "this token")
    if occasion.startswith("market_cap_crossed_"):
        return f"{name} just crossed {_fmt_usd(float(occasion.rsplit('_', 1)[1]))} market cap. Community's been busy 👀"
    if occasion == "graduated_from_bonding_curve":
        return f"{name} graduated from the pump.fun bonding curve and is now trading on the open market 🎓"
    if occasion == "launch_announcement":
        return f"Say hi to {name} 👋 {t.description[:120]}".strip()
    return f"{name} is live on Solana. {t.description[:140]}".strip()
