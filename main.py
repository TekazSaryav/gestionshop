from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timezone


import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.database import Database
from core.helpers import safe_json, tekaz_embed, utcnow_iso
from core.logger import setup_logging
from core.webhooks import start_webhook_server

COGS = [
    "cogs.admin",
    "cogs.tickets",
    "cogs.orders",
    "cogs.proofs",
    "cogs.stock",
    "cogs.vouches",
    "cogs.stats",
    "cogs.utils",
    "cogs.catalog",
]


def _parse_restart_interval(raw: str | None) -> int:
    if not raw:
        return 0
    value = raw.strip().lower()
    if value.isdigit():
        return int(value)
    units = {"s": 1, "m": 60, "h": 3600}
    suffix = value[-1]
    if suffix in units and value[:-1].isdigit():
        return int(value[:-1]) * units[suffix]
    raise ValueError("AUTO_RESTART_INTERVAL invalide. Ex: 3600, 30m, 6h")


class TekazBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.start_time = datetime.now(timezone.utc)
        self.db = Database(os.getenv("DATABASE_PATH", "tekaz_shop.db"))
        self.log = logging.getLogger("tekaz")
        self.order_counter_start = int(os.getenv("ORDER_COUNTER_START", "1"))
        self.webhook_runner = None
        self.restart_interval = _parse_restart_interval(os.getenv("AUTO_RESTART_INTERVAL"))
        self.restart_requested = False
        self._restart_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await self.db.connect()
        for cog in COGS:
            await self.load_extension(cog)
        guild_id = os.getenv("DEFAULT_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.webhook_runner = await start_webhook_server(self)
        if self.restart_interval > 0:
            self._restart_task = asyncio.create_task(self._auto_restart_loop())

    async def _auto_restart_loop(self) -> None:
        await asyncio.sleep(self.restart_interval)
        self.restart_requested = True
        self.log.warning("Restart automatique déclenché après %s secondes", self.restart_interval)
        await self.close()


    async def close(self) -> None:
        if self._restart_task and self._restart_task is not asyncio.current_task():
            self._restart_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._restart_task
        if self.webhook_runner:
            await self.webhook_runner.cleanup()
        await super().close()

    async def on_ready(self) -> None:
        self.log.info("Bot connecté en tant que %s", self.user)

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        self.log.exception("Erreur commande: %s", error)
        embed = tekaz_embed("❌ Error", "Une erreur est survenue. Merci de réessayer ou contacter le staff.")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def next_order_id(self, guild_id: int) -> str:
        rows = await self.db.fetchall("SELECT order_id FROM orders WHERE guild_id = ?", (guild_id,))
        next_num = max([int(r["order_id"].split("-")[-1]) for r in rows], default=self.order_counter_start - 1) + 1
        year = datetime.now(timezone.utc).year
        return f"TKZ-{year}-{next_num:06d}"

    async def next_proof_id(self) -> str:
        rows = await self.db.fetchall("SELECT proof_id FROM proofs")
        next_num = max([int(r["proof_id"].split("-")[-1]) for r in rows], default=0) + 1
        return f"PROOF-TKZ-{next_num:06d}"

    async def audit(self, guild_id: int, actor_id: int, action: str, target: str = "", metadata: dict | None = None) -> None:
        await self.db.execute(
            "INSERT INTO audit_logs(guild_id, actor_id, action, target, metadata_json, created_at) VALUES(?,?,?,?,?,?)",
            (guild_id, actor_id, action, target, safe_json(metadata or {}), utcnow_iso()),
        )
        config = await self.db.fetchone("SELECT logs_channel_id FROM config WHERE guild_id = ?", (guild_id,))
        if config and config["logs_channel_id"]:
            channel = self.get_channel(config["logs_channel_id"])
            if isinstance(channel, discord.TextChannel):
                embed = tekaz_embed("🧾 Audit Log", f"**Action:** {action}\n**Actor:** <@{actor_id}>\n**Target:** {target}")
                if metadata:
                    embed.add_field(name="Metadata", value=f"```json\n{safe_json(metadata)[:900]}\n```", inline=False)
                await channel.send(embed=embed)


async def main() -> None:
    load_dotenv()
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant dans .env")
    while True:
        bot = TekazBot()
        async with bot:
            await bot.start(token)
        if not bot.restart_requested:
            break
        logging.getLogger("tekaz").info("Redémarrage du bot...")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
