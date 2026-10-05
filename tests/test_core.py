import asyncio
import json

import httpx
import pytest

from memepromo import agent as agent_mod
from memepromo.agent import CampaignRunner
from memepromo.config import Settings
from memepromo.content import Copywriter, finalize
from memepromo.db import DB
from memepromo.token_data import InvalidAddress, TokenInfo, detect_milestones, fetch_token, validate_address

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"

DEX = {"pairs": [
    {"chainId": "solana", "dexId": "raydium", "url": "https://dexscreener.com/solana/pair1",
     "baseToken": {"address": MINT, "name": "Popcat", "symbol": "POPCAT"},
     "priceUsd": "0.5", "marketCap": 480000, "liquidity": {"usd": 90000}, "volume": {"h24": 300000},
     "priceChange": {"h1": 4.2, "h24": -3.1},
     "info": {"socials": [{"type": "twitter", "url": "https://x.com/popcat"}]}},
    {"chainId": "solana", "dexId": "meteora", "liquidity": {"usd": 10}, "baseToken": {"address": MINT}},
    {"chainId": "ethereum", "dexId": "uniswap", "liquidity": {"usd": 1e9}, "baseToken": {"address": MINT}},
]}
PUMP = {"mint": MINT, "name": "Popcat", "symbol": "POPCAT", "description": "cat that pops",
        "complete": True, "telegram": "https://t.me/popcat"}


def mock_client(dex=DEX, pump=PUMP):
    def handler(req: httpx.Request):
        if "dexscreener" in req.url.host:
            return httpx.Response(200, json=dex)
        if "pump.fun" in req.url.host:
            return httpx.Response(200, json=pump) if pump else httpx.Response(404)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_validate_address():
    assert validate_address(f"  {MINT} ") == MINT
    for bad in ["", "0x1234", "O" * 40, MINT + "!"]:
        with pytest.raises(InvalidAddress):
            validate_address(bad)


def test_fetch_token_merges_sources():
    info = asyncio.run(fetch_token(MINT, mock_client()))
    assert info.symbol == "POPCAT" and info.launchpad == "raydium"
    assert info.liquidity_usd == 90000  # picked deepest *solana* pool, ignored ethereum
    assert info.graduated is True and info.telegram == "https://t.me/popcat"
    assert info.twitter == "https://x.com/popcat"
    assert info.sources == ["dexscreener", "pump.fun"]


def test_milestones():
    prev = TokenInfo(address=MINT, graduated=False, market_cap_usd=90_000)
    cur = TokenInfo(address=MINT, graduated=True, market_cap_usd=260_000)
    assert detect_milestones(prev, cur) == ["graduated_from_bonding_curve", "market_cap_crossed_100000",
                                            "market_cap_crossed_250000"]
    assert detect_milestones(None, cur) == ["launch_announcement"]


def test_finalize_enforces_rules():
    s = Settings(paid_promo=True)
    t = TokenInfo(address=MINT, chart_url="https://dexscreener.com/x")
    out = finalize("gm frens, the cat is popping " * 20, t, "x", s)
    assert len(out) <= 280 and out.endswith("#ad Not financial advice. DYOR.") and f"CA: {MINT}" in out
    assert "dexscreener" not in out  # chart link dropped on short channels
    assert "dexscreener" in finalize("hello cat world, popping today", t, "telegram", s)
    assert finalize("This is guaranteed 100x, trust me bro", t, "telegram", s) is None


class FakeMessages:
    def __init__(self, posts):
        self.posts, self.calls = posts, []

    async def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps({"posts": self.posts})
        block = type("B", (), {"type": "text", "text": text})()
        return type("R", (), {"stop_reason": "end_turn", "content": [block]})()


class FakeClient:
    def __init__(self, posts):
        self.beta = type("Beta", (), {})()
        self.beta.messages = FakeMessages(posts)


def test_agent_step_dry_run_and_rate_limit(tmp_path, monkeypatch):
    async def fake_fetch(address):
        return await fetch_token(address, mock_client())
    monkeypatch.setattr(agent_mod, "fetch_token", fake_fetch)
    db = DB(str(tmp_path / "t.db"))
    settings = Settings(dry_run=True)
    client = FakeClient([{"channel": "x", "text": "POPCAT says hi"},
                         {"channel": "telegram", "text": "Welcome to the POPCAT community"},
                         {"channel": "discord", "text": "100x guaranteed lol"}])
    cid = db.create_campaign(MINT, "", ["x", "telegram", "discord"], 120, dry_run=False)
    runner = CampaignRunner(cid, db, settings, Copywriter(settings, client))

    made = asyncio.run(runner.step())
    assert made == 2  # discord post rejected by compliance filter
    posts = db.posts(cid)
    assert {p["status"] for p in posts} == {"dry_run"}
    assert {p["occasion"] for p in posts} == {"launch_announcement"}
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"

    # Second pass right away: x and telegram are inside their interval, only discord is due.
    asyncio.run(runner.step())
    assert client.beta.messages.calls[1]["output_config"]["format"]["schema"]["properties"]["posts"]["items"]["properties"]["channel"]["enum"] == ["discord"]


def test_template_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    info = TokenInfo(address=MINT, symbol="POPCAT", description="cat that pops")
    posts = asyncio.run(Copywriter(Settings()).write(info, ["x", "bluesky"], "launch_announcement", []))
    assert set(posts) == {"x", "bluesky"} and "POPCAT" in posts["x"]
