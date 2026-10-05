"""CLI:  python -m memepromo preview <address> [channel ...]
         python -m memepromo serve [--port 8000]"""
import asyncio
import sys

from .config import get_settings
from .content import Copywriter
from .token_data import fetch_token


async def preview(address: str, channels: list[str]) -> None:
    info = await fetch_token(address)
    print(f"{info.name} (${info.symbol}) via {', '.join(info.sources)}\n")
    posts = await Copywriter(get_settings()).write(info, channels, "launch_announcement", [])
    for channel, text in posts.items():
        print(f"--- {channel} ({len(text)} chars) ---\n{text}\n")


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "preview":
        asyncio.run(preview(args[1], args[2:] or ["x", "telegram", "discord", "bluesky", "farcaster"]))
    elif args and args[0] == "serve":
        import uvicorn
        port = int(args[args.index("--port") + 1]) if "--port" in args else 8000
        uvicorn.run("memepromo.app:app", host="127.0.0.1", port=port)
    else:
        print(__doc__)


main()
