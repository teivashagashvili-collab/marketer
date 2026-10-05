"""The autonomous loop. One asyncio task per campaign:

    watch token -> spot milestones -> decide which channels are due -> write posts -> publish -> log

It runs unattended until stopped, inside hard limits from Settings that a campaign
can't override (minimum interval, daily cap per channel).
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time

from .channels import ALL_CHANNELS, ChannelError
from .config import Settings
from .content import Copywriter
from .db import DB
from .token_data import TokenInfo, detect_milestones, fetch_token

log = logging.getLogger("memepromo.agent")

# Rotating angles for regular posts so the feed doesn't repeat itself.
ANGLES = [
    "what the token is about and its meme",
    "market stats recap (only the numbers given)",
    "community vibe check, invite people to the community links",
    "a short joke riffing on the token's theme",
    "where to find the chart and socials",
]
MILESTONE_MIN_GAP_S = 10 * 60


class CampaignRunner:
    def __init__(self, cid: int, db: DB, settings: Settings, copywriter: Copywriter, tick_seconds: int = 60):
        self.cid = cid
        self.db = db
        self.settings = settings
        self.copywriter = copywriter
        self.tick = tick_seconds
        self.angles = itertools.cycle(ANGLES)
        self.prev: TokenInfo | None = None

    def _due(self, channel: str, interval_s: float, milestone: bool) -> bool:
        now = time.time()
        if self.db.posts_since(self.cid, channel, now - 86400) >= self.settings.max_posts_per_channel_per_day:
            return False
        last = self.db.last_post_time(self.cid, channel)
        if last is None:
            return True
        gap = now - last
        return gap >= (MILESTONE_MIN_GAP_S if milestone else interval_s)

    async def step(self) -> int:
        """One pass of the loop. Returns how many posts were made (or logged in dry run)."""
        camp = self.db.campaign(self.cid)
        if not camp or camp["status"] != "running":
            return 0
        info = await fetch_token(camp["address"])
        prev = self.prev
        if prev is None and camp["snapshot"]:
            prev = TokenInfo(**camp["snapshot"])
        self.prev = info
        self.db.save_snapshot(self.cid, info.to_dict(), info.symbol)

        milestones = detect_milestones(prev, info)
        occasion = milestones[0] if milestones else f"regular post, angle: {next(self.angles)}"
        interval_s = max(camp["interval_minutes"], self.settings.min_interval_minutes) * 60
        due = [c for c in camp["channels"] if self._due(c, interval_s, bool(milestones))]
        if not due:
            return 0

        recent = [p["text"] for p in self.db.posts(self.cid, limit=10)]
        posts = await self.copywriter.write(info, due, occasion, recent)
        dry = camp["dry_run"] or self.settings.dry_run
        made = 0
        for channel, text in posts.items():
            adapter = ALL_CHANNELS.get(channel)
            if dry or adapter is None:
                self.db.log_post(self.cid, channel, occasion, text, "dry_run")
                made += 1
                continue
            if not adapter.configured():
                self.db.log_post(self.cid, channel, occasion, text, "failed", f"missing {', '.join(adapter.missing())}")
                continue
            try:
                result = await adapter.post(text)
                self.db.log_post(self.cid, channel, occasion, text, "sent", result)
                made += 1
            except ChannelError as e:
                self.db.log_post(self.cid, channel, occasion, text, "failed", str(e))
        return made

    async def run(self) -> None:
        while True:
            camp = self.db.campaign(self.cid)
            if not camp or camp["status"] != "running":
                return
            try:
                await self.step()
            except Exception:  # keep the agent alive through API hiccups
                log.exception("campaign %s step failed", self.cid)
            await asyncio.sleep(self.tick)


class Manager:
    """Starts/stops runners and resumes running campaigns after a restart."""

    def __init__(self, db: DB, settings: Settings, copywriter: Copywriter | None = None):
        self.db = db
        self.settings = settings
        self.copywriter = copywriter or Copywriter(settings)
        self.tasks: dict[int, asyncio.Task] = {}

    def start(self, cid: int) -> None:
        if cid in self.tasks and not self.tasks[cid].done():
            return
        self.db.set_status(cid, "running")
        runner = CampaignRunner(cid, self.db, self.settings, self.copywriter)
        self.tasks[cid] = asyncio.create_task(runner.run())

    def stop(self, cid: int) -> None:
        self.db.set_status(cid, "stopped")
        task = self.tasks.pop(cid, None)
        if task:
            task.cancel()

    def resume_all(self) -> None:
        for camp in self.db.campaigns(status="running"):
            self.start(camp["id"])
