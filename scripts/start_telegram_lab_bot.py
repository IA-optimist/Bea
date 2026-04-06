"""
Standalone launcher for the JarvisMax Telegram AI lab bot.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    load_dotenv(repo_root / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from integrations.telegram_lab_bot import TelegramLabBot, TelegramLabConfig

    config = TelegramLabConfig.from_env(repo_root=repo_root)
    TelegramLabBot(config).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
