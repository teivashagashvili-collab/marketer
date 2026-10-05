"""Settings, read from environment variables only. Secrets never touch disk here."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("MEMEPROMO_MODEL", "claude-opus-5-5"))
    dry_run: bool = field(default_factory=lambda: _bool("MEMEPROMO_DRY_RUN", True))
    disclaimer: str = field(default_factory=lambda: os.getenv("MEMEPROMO_DISCLAIMER", "Not financial advice. DYOR."))
    paid_promo: bool = field(default_factory=lambda: _bool("MEMEPROMO_PAID_PROMO", False))
    db_path: str = field(default_factory=lambda: os.getenv("MEMEPROMO_DB", "memepromo.sqlite3"))

    # Hard ceilings the agent can never exceed, whatever a campaign asks for.
    min_interval_minutes: int = 30
    max_posts_per_channel_per_day: int = 12


def get_settings() -> Settings:
    return Settings()
