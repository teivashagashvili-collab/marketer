"""Token intake: turn a Solana contract address into a TokenInfo snapshot.

Sources (both public, no key needed):
- DexScreener: price, market cap, liquidity, volume, price change, DEX + pair URL.
  Covers pump.fun, PumpSwap, Raydium, Meteora, Orca, Moonshot, LaunchLab, etc.
- pump.fun frontend API: name, symbol, description, socials, bonding-curve status
  for tokens launched there (best effort; it is unofficial and may change).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import httpx

BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"
PUMPFUN_URL = "https://frontend-api-v3.pump.fun/coins/{address}"


class InvalidAddress(ValueError):
    pass


class TokenNotFound(LookupError):
    pass


@dataclass
class TokenInfo:
    address: str
    name: str = ""
    symbol: str = ""
    description: str = ""
    image_url: str = ""
    website: str = ""
    twitter: str = ""
    telegram: str = ""
    launchpad: str = ""          # e.g. "pump.fun", "raydium", "meteora"
    graduated: bool | None = None  # pump.fun bonding curve completed?
    price_usd: float | None = None
    market_cap_usd: float | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None
    price_change_1h_pct: float | None = None
    price_change_24h_pct: float | None = None
    chart_url: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_address(address: str) -> str:
    address = address.strip()
    if not BASE58_RE.match(address):
        raise InvalidAddress(f"Not a valid Solana address: {address!r}")
    return address


def _f(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def apply_dexscreener(info: TokenInfo, payload: dict) -> None:
    pairs = [p for p in (payload.get("pairs") or []) if p.get("chainId") == "solana"]
    if not pairs:
        return
    # The deepest pool is the most representative price.
    best = max(pairs, key=lambda p: _f((p.get("liquidity") or {}).get("usd")) or 0)
    base = best.get("baseToken") or {}
    if base.get("address") == info.address:
        info.name = info.name or base.get("name", "")
        info.symbol = info.symbol or base.get("symbol", "")
    info.launchpad = info.launchpad or best.get("dexId", "")
    info.price_usd = _f(best.get("priceUsd"))
    info.market_cap_usd = _f(best.get("marketCap")) or _f(best.get("fdv"))
    info.liquidity_usd = _f((best.get("liquidity") or {}).get("usd"))
    info.volume_24h_usd = _f((best.get("volume") or {}).get("h24"))
    info.price_change_1h_pct = _f((best.get("priceChange") or {}).get("h1"))
    info.price_change_24h_pct = _f((best.get("priceChange") or {}).get("h24"))
    info.chart_url = best.get("url", "")
    meta = best.get("info") or {}
    info.image_url = info.image_url or meta.get("imageUrl", "")
    for site in meta.get("websites") or []:
        info.website = info.website or site.get("url", "")
    for social in meta.get("socials") or []:
        kind, url = social.get("type"), social.get("url", "")
        if kind == "twitter":
            info.twitter = info.twitter or url
        elif kind == "telegram":
            info.telegram = info.telegram or url
    info.sources.append("dexscreener")


def apply_pumpfun(info: TokenInfo, payload: dict) -> None:
    if not payload or payload.get("mint") != info.address:
        return
    info.name = payload.get("name") or info.name
    info.symbol = payload.get("symbol") or info.symbol
    info.description = payload.get("description") or info.description
    info.image_url = payload.get("image_uri") or info.image_url
    info.website = payload.get("website") or info.website
    info.twitter = payload.get("twitter") or info.twitter
    info.telegram = payload.get("telegram") or info.telegram
    info.graduated = bool(payload.get("complete"))
    if info.market_cap_usd is None:
        info.market_cap_usd = _f(payload.get("usd_market_cap"))
    if not info.launchpad or info.launchpad in ("pumpfun", "pumpswap"):
        info.launchpad = "pump.fun"
    info.sources.append("pump.fun")


async def fetch_token(address: str, client: httpx.AsyncClient | None = None) -> TokenInfo:
    address = validate_address(address)
    info = TokenInfo(address=address)
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": "memepromo/0.1"})
    try:
        try:
            r = await client.get(DEXSCREENER_URL.format(address=address))
            if r.status_code == 200:
                apply_dexscreener(info, r.json())
        except httpx.HTTPError:
            pass
        try:
            r = await client.get(PUMPFUN_URL.format(address=address))
            if r.status_code == 200:
                apply_pumpfun(info, r.json())
        except (httpx.HTTPError, ValueError):
            pass
    finally:
        if own_client:
            await client.aclose()
    if not info.sources:
        raise TokenNotFound(f"No market data found for {address} on DexScreener or pump.fun")
    return info


def detect_milestones(prev: TokenInfo | None, cur: TokenInfo) -> list[str]:
    """Events worth a post of their own. Facts only, no predictions."""
    if prev is None:
        return ["launch_announcement"]
    events = []
    if prev.graduated is False and cur.graduated:
        events.append("graduated_from_bonding_curve")
    for threshold in (100_000, 250_000, 500_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000):
        if (prev.market_cap_usd or 0) < threshold <= (cur.market_cap_usd or 0):
            events.append(f"market_cap_crossed_{threshold}")
    return events
