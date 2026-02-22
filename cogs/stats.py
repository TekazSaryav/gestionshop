from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed
from core.permissions import is_staff


class StatsCog(commands.Cog, name="stats"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="stats", description="Stats globales Tekaz")
    @is_staff()
    async def stats(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        gid = interaction.guild.id
        orders = await self.bot.db.fetchone("SELECT COUNT(*) AS c FROM orders WHERE guild_id = ?", (gid,))
        proofs = await self.bot.db.fetchone("SELECT COUNT(*) AS c FROM proofs WHERE guild_id = ?", (gid,))
        tickets = await self.bot.db.fetchone("SELECT COUNT(*) AS c FROM tickets WHERE guild_id = ?", (gid,))
        vouches = await self.bot.db.fetchone("SELECT COUNT(*) AS c FROM vouches WHERE guild_id = ?", (gid,))
        embed = tekaz_embed("📊 Tekaz Stats")
        embed.add_field(name="Orders", value=str(orders["c"]))
        embed.add_field(name="Proofs", value=str(proofs["c"]))
        embed.add_field(name="Tickets", value=str(tickets["c"]))
        embed.add_field(name="Vouches", value=str(vouches["c"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
