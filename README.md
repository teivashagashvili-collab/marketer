# Meme Marketer

Paste a Solana memecoin contract address, pick channels, and an agent promotes it on its own: it watches the token, writes fresh posts with Claude, and publishes them on a schedule to the accounts and channels you own.

## How it works

```
contract address
      │
      ▼
token intake ──── DexScreener (price, mcap, liquidity, volume, DEX, chart; any Solana launchpad)
(token_data.py)   pump.fun API (name, description, socials, bonding-curve status)
      │
      ▼
agent loop ────── every minute: refresh data, detect milestones (launch, graduated from
(agent.py)        bonding curve, market cap crossing 100K/250K/500K/1M/5M/10M/50M),
      │           decide which channels are due (interval + daily cap)
      ▼
copywriter ────── Claude writes one post per due channel, sized to its limit, varied
(content.py)      angles, no repeats; code appends CA + disclaimer and drops banned claims
      │
      ▼
channel adapters ─ X · Telegram · Discord · Bluesky · Farcaster   (channels/)
      │
      ▼
SQLite post log ── dashboard (app.py): start/stop campaigns, preview posts, read the log
```

Without an `ANTHROPIC_API_KEY` the copywriter falls back to simple templates, so you can try everything offline.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env            # fill in what you have; blank channels are just skipped
set -a; source .env; set +a
python -m memepromo preview <CONTRACT_ADDRESS>   # see the posts it would write
python -m memepromo serve                        # dashboard at http://127.0.0.1:8000
pytest -q                                        # 6 tests, no network needed
```

`MEMEPROMO_DRY_RUN=true` (the default) means nothing is ever sent; posts are only logged. Set it to `false` once the previews look right, and untick "Dry run first" on a campaign.

## Channel coverage

| Channel | How | Status |
|---|---|---|
| X | Official v2 API, your account (OAuth 1.0a). Needs a paid tier with write access. | Built |
| Telegram | Bot API, posting in a channel/group you own with the bot as admin | Built |
| Discord | Webhook in a server you admin | Built |
| Bluesky | AT Protocol with an app password | Built |
| Farcaster | Neynar API with your signer | Built |
| Reddit | Official API, but nearly every crypto subreddit bans self-promo; only your own subreddit is safe | Easy to add for your own sub |
| TikTok / Instagram / YouTube | APIs need business approval and media (video/image), not text | Later, with image/video generation |
| Other people's Telegram groups / Discord servers, DMs, auto-replies to strangers, multiple accounts | Not built on purpose: these break each platform's rules and get accounts and bots banned fast | Won't do |

## Built-in limits

- Minimum 30 minutes between regular posts per channel, max 12 posts per channel per day (`config.py`). Milestone posts can jump the interval, but not the daily cap, and not more often than every 10 minutes.
- Every post gets `CA: <address>` and the disclaimer appended in code. Set `MEMEPROMO_PAID_PROMO=true` to add `#ad` when you're paid to promote someone else's token; undisclosed paid promotion is illegal in the US/EU/UK.
- Posts with return promises ("guaranteed", "100x", "risk-free" …) are dropped before sending.
- Credentials come from environment variables only; nothing secret is written to disk.

## Layout

```
memepromo/
  config.py       settings + hard limits
  token_data.py   DexScreener + pump.fun intake, milestone detection
  content.py      Claude copywriter (claude-opus-5-5, structured output, refusal fallback)
  agent.py        per-campaign autonomous loop + manager
  db.py           SQLite campaigns + post log
  app.py          FastAPI dashboard
  channels/       x, telegram, discord, bluesky, farcaster adapters
tests/test_core.py
```

## Next steps

1. Image generation per post (token logo remixes) so X/Telegram posts carry media.
2. Reddit adapter for your own subreddit.
3. Deploy (Railway/Fly/VPS) so the agent runs 24/7, with a login on the dashboard.
4. Engagement analytics: pull likes/reposts back in and let the agent favour angles that perform.
