"""Channel adapter interface. Each adapter posts to an account or channel the user owns."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ChannelError(RuntimeError):
    pass


class Channel(ABC):
    name: str = ""
    env_vars: tuple[str, ...] = ()

    def configured(self) -> bool:
        return all(os.getenv(v) for v in self.env_vars)

    def missing(self) -> list[str]:
        return [v for v in self.env_vars if not os.getenv(v)]

    @abstractmethod
    async def post(self, text: str) -> str:
        """Publish text and return a URL or id for the post. Raise ChannelError on failure."""
