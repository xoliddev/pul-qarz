"""Settings from environment variables (see .env.example). Nothing secret has a default."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader so beginners do not need extra packages. Real env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    bot_token: str
    webapp_url: str = ""
    db_path: str = "data/pulqarz.db"
    host: str = "0.0.0.0"  # noqa: S104 - the container must listen on all interfaces
    port: int = 8080
    initdata_max_age: int = 3600
    invite_days: int = 7
    rate_per_minute: int = 30
    reminder_interval: int = 60

    @classmethod
    def from_env(cls, dotenv: Path | None = Path(".env")) -> Settings:
        if dotenv is not None:
            _load_dotenv(dotenv)
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token or ":" not in token:
            raise SystemExit("BOT_TOKEN is missing. Copy .env.example to .env and paste the token from @BotFather.")
        url = os.environ.get("WEBAPP_URL", "").strip().rstrip("/")
        if url and not url.startswith("https://"):
            raise SystemExit("WEBAPP_URL must start with https:// (Telegram opens Mini Apps only over HTTPS).")
        return cls(
            bot_token=token,
            webapp_url=url,
            db_path=os.environ.get("DB_PATH", cls.db_path),
            host=os.environ.get("HOST", cls.host),
            port=int(os.environ.get("PORT", cls.port)),
            initdata_max_age=int(os.environ.get("INITDATA_MAX_AGE", cls.initdata_max_age)),
            invite_days=int(os.environ.get("INVITE_DAYS", cls.invite_days)),
            rate_per_minute=int(os.environ.get("RATE_PER_MINUTE", cls.rate_per_minute)),
            reminder_interval=int(os.environ.get("REMINDER_INTERVAL", cls.reminder_interval)),
        )
