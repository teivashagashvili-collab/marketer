"""Dashboard: paste a contract address, pick channels, start the agent, watch the post log.

Run:  uvicorn memepromo.app:app --port 8000
"""
from __future__ import annotations

import html
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from .agent import Manager
from .channels import ALL_CHANNELS
from .config import get_settings
from .content import Copywriter
from .db import DB
from .token_data import InvalidAddress, TokenNotFound, fetch_token

settings = get_settings()
db = DB(settings.db_path)
manager = Manager(db, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    manager.resume_all()
    yield
    for task in manager.tasks.values():
        task.cancel()


app = FastAPI(title="Meme Marketer", lifespan=lifespan)

CSS = """
:root{--bg:#0f1115;--fg:#e8e8ea;--muted:#9aa0a6;--card:#181b22;--line:#2a2f3a;--accent:#7c5cff;--ok:#2fbf71;--bad:#e5484d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 16px}h2{font-size:16px;margin:24px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
input[type=text],input[type=number]{width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:#0b0d11;color:var(--fg)}
label{display:inline-flex;gap:6px;align-items:center;margin:6px 14px 6px 0}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 16px;cursor:pointer}
button.secondary{background:transparent;border:1px solid var(--line);color:var(--fg)}
.muted{color:var(--muted);font-size:13px}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
pre{white-space:pre-wrap;word-break:break-word;margin:6px 0 0;font:13px/1.45 ui-monospace,monospace}
.pill{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line)}
a{color:var(--accent)}.sent{color:var(--ok)}.failed{color:var(--bad)}.dry_run{color:var(--muted)}
"""


def page(body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                        f"<title>Meme Marketer</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


@app.get("/", response_class=HTMLResponse)
async def home():
    boxes = "".join(
        f"<label><input type=checkbox name=channels value={n} {'checked' if ch.configured() else ''}>{n}"
        f"{'' if ch.configured() else ' <span class=muted>(not set up)</span>'}</label>"
        for n, ch in ALL_CHANNELS.items()
    )
    camps = "".join(
        f"<div class=card><div class=row><b>${esc(c['symbol']) or '?'}</b><span class=muted>{esc(c['address'])}</span>"
        f"<span class=pill>{esc(c['status'])}</span>{'<span class=pill>dry run</span>' if c['dry_run'] or settings.dry_run else ''}</div>"
        f"<div class=muted>every {c['interval_minutes']} min on {', '.join(c['channels'])}</div>"
        f"<div class=row style='margin-top:8px'><a href=/campaigns/{c['id']}><button class=secondary>Post log</button></a>"
        + (f"<form method=post action=/campaigns/{c['id']}/stop><button class=secondary>Stop</button></form>" if c['status'] == 'running'
           else f"<form method=post action=/campaigns/{c['id']}/start><button class=secondary>Resume</button></form>")
        + "</div></div>"
        for c in db.campaigns()
    ) or "<p class=muted>No campaigns yet.</p>"
    global_dry = "<p class=muted>Global dry run is ON (MEMEPROMO_DRY_RUN). Nothing will be sent anywhere.</p>" if settings.dry_run else ""
    return page(f"""
<h1>Meme Marketer</h1>{global_dry}
<form class=card method=post action=/campaigns>
  <input type=text name=address placeholder="Paste Solana token contract address" required>
  <div style="margin:10px 0">{boxes}</div>
  <div class=row><label>Post every <input type=number name=interval_minutes value=120 min={settings.min_interval_minutes} style="width:90px"> minutes</label>
  <label><input type=checkbox name=dry_run value=1 checked>Dry run first</label></div>
  <div class=row><button>Start agent</button><button class=secondary formaction=/preview>Preview posts</button></div>
</form>
<h2>Campaigns</h2>{camps}""")


@app.post("/preview", response_class=HTMLResponse)
async def preview(address: str = Form(...), channels: list[str] = Form(default=[])):
    try:
        info = await fetch_token(address)
    except (InvalidAddress, TokenNotFound) as e:
        raise HTTPException(400, str(e))
    posts = await Copywriter(settings).write(info, channels or list(ALL_CHANNELS), "launch_announcement", [])
    cards = "".join(f"<div class=card><span class=pill>{esc(c)}</span><pre>{esc(t)}</pre></div>" for c, t in posts.items())
    return page(f"<h1>Preview for ${esc(info.symbol)}</h1><p class=muted>Sources: {', '.join(info.sources)}</p>{cards}<a href=/>Back</a>")


@app.post("/campaigns")
async def create_campaign(address: str = Form(...), channels: list[str] = Form(default=[]),
                          interval_minutes: int = Form(120), dry_run: str | None = Form(None)):
    channels = [c for c in channels if c in ALL_CHANNELS]
    if not channels:
        raise HTTPException(400, "Pick at least one channel")
    try:
        info = await fetch_token(address)
    except (InvalidAddress, TokenNotFound) as e:
        raise HTTPException(400, str(e))
    interval = max(interval_minutes, settings.min_interval_minutes)
    cid = db.create_campaign(info.address, info.symbol, channels, interval, bool(dry_run))
    manager.start(cid)
    return RedirectResponse("/", status_code=303)


@app.post("/campaigns/{cid}/stop")
async def stop(cid: int):
    manager.stop(cid)
    return RedirectResponse("/", status_code=303)


@app.post("/campaigns/{cid}/start")
async def start(cid: int):
    if not db.campaign(cid):
        raise HTTPException(404)
    manager.start(cid)
    return RedirectResponse("/", status_code=303)


@app.get("/campaigns/{cid}", response_class=HTMLResponse)
async def campaign_log(cid: int):
    camp = db.campaign(cid)
    if not camp:
        raise HTTPException(404)
    rows = "".join(
        f"<div class=card><div class=row><span class=pill>{esc(p['channel'])}</span><span class='{esc(p['status'])}'>{esc(p['status'])}</span>"
        f"<span class=muted>{time.strftime('%Y-%m-%d %H:%M', time.localtime(p['created_at']))} · {esc(p['occasion'])}</span></div>"
        f"<pre>{esc(p['text'])}</pre><div class=muted>{esc(p['result'])}</div></div>"
        for p in db.posts(cid)
    ) or "<p class=muted>No posts yet. The agent checks the token every minute.</p>"
    return page(f"<h1>${esc(camp['symbol'])} post log</h1><p><a href=/>Back</a></p>{rows}")


@app.get("/api/campaigns")
async def api_campaigns():
    return db.campaigns()
