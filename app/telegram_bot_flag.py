from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FLAG_FILE = PROJECT_ROOT / 'telegram_bot_enabled.flag'

FlagSource = Literal['flag_file', 'env_var']


def _read_flag_file() -> Tuple[Optional[bool], Optional[FlagSource]]:
    """Return the boolean stored in the flag file if it exists and is valid."""
    try:
        raw_value = FLAG_FILE.read_text().strip().lower()
    except FileNotFoundError:
        return None, None

    if raw_value in {'true', 'false'}:
        return raw_value == 'true', 'flag_file'

    return None, 'flag_file'


def get_telegram_bot_flag(default: bool = True) -> Tuple[bool, FlagSource]:
    """Return the current flag value and its source."""
    flag_value, source = _read_flag_file()
    if flag_value is not None and source is not None:
        return flag_value, source

    env_value = os.getenv('ENABLE_BOT', 'true').lower() == 'true'
    return env_value, 'env_var'


def is_telegram_bot_enabled(default: bool = True) -> bool:
    """Return whether the telegram bot should be enabled."""
    value, _ = get_telegram_bot_flag(default=default)
    return value
