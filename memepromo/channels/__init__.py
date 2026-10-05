from .base import Channel, ChannelError
from .bluesky import BlueskyChannel
from .discord import DiscordChannel
from .farcaster import FarcasterChannel
from .telegram import TelegramChannel
from .x import XChannel

ALL_CHANNELS: dict[str, Channel] = {
    c.name: c for c in (XChannel(), TelegramChannel(), DiscordChannel(), BlueskyChannel(), FarcasterChannel())
}

__all__ = ["ALL_CHANNELS", "Channel", "ChannelError"]
