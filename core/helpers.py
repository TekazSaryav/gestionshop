from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from core.constants import TEKAZ_COLOR, TEKAZ_FOOTER


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tekaz_embed(title: str, description: str | None = None, *, color: int = TEKAZ_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=TEKAZ_FOOTER)
    return embed


def safe_json(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str)


def parse_json(raw: str | None, default: Any) -> Any:
    import json

    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
