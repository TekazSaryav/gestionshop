from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed
from core.permissions import is_staff


class Pager(discord.ui.View):
    def __init__(self, pages: list[str]) -> None:
        super().__init__(timeout=120)
        self.pages = pages
        self.index = 0

    def current_embed(self) -> discord.Embed:
        return tekaz_embed(f"Page {self.index + 1}/{len(self.pages)}", self.pages[self.index])

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


class UtilsCog(commands.Cog, name="utils"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="search", description="Rechercher commandes")
    @is_staff()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        assert interaction.guild
        rows = await self.bot.db.fetchall(
            "SELECT * FROM orders WHERE guild_id = ? AND (order_id LIKE ? OR status LIKE ? OR product LIKE ?) ORDER BY created_at DESC LIMIT 50",
            (interaction.guild.id, f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        if not rows:
            await interaction.response.send_message("Aucun résultat", ephemeral=True)
            return
        lines = [f"`{r['order_id']}` • <@{r['user_id']}> • {r['status']} • {r['product']}" for r in rows]
        chunks = ["\n".join(lines[i : i + 10]) for i in range(0, len(lines), 10)]
        view = Pager(chunks)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilsCog(bot))
