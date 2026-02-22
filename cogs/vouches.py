from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed, utcnow_iso


class VouchModal(discord.ui.Modal, title="Leave a Vouch"):
    rating = discord.ui.TextInput(label="Note 1-5", required=True, max_length=1)
    comment = discord.ui.TextInput(label="Commentaire", required=True, style=discord.TextStyle.paragraph)
    order_id = discord.ui.TextInput(label="order_id (optionnel)", required=False)

    def __init__(self, cog: "VouchesCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_vouch(interaction, str(self.rating), str(self.comment), str(self.order_id))


class VouchPanelView(discord.ui.View):
    def __init__(self, cog: "VouchesCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="⭐ Leave a Vouch", style=discord.ButtonStyle.success)
    async def leave_vouch(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(VouchModal(self.cog))


class VouchesCog(commands.Cog, name="vouches"):
    vouch = app_commands.Group(name="vouch", description="Avis clients")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cooldown_h = int(os.getenv("VOUCH_COOLDOWN_HOURS", "24"))

    @vouch.command(name="panel")
    async def panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=tekaz_embed("⭐ Tekaz Vouches", "Partage ton avis."), view=VouchPanelView(self))

    async def handle_vouch(self, interaction: discord.Interaction, rating_raw: str, comment: str, order_id: str) -> None:
        assert interaction.guild
        try:
            rating = int(rating_raw)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Note invalide", ephemeral=True)
            return

        row = await self.bot.db.fetchone(
            "SELECT created_at FROM vouches WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1",
            (interaction.guild.id, interaction.user.id),
        )
        if row:
            last = datetime.fromisoformat(row["created_at"])
            if datetime.now(timezone.utc) - last < timedelta(hours=self.cooldown_h):
                await interaction.response.send_message("Cooldown vouch actif.", ephemeral=True)
                return

        await self.bot.db.execute(
            "INSERT INTO vouches(guild_id,user_id,rating,comment,order_id,created_at) VALUES(?,?,?,?,?,?)",
            (interaction.guild.id, interaction.user.id, rating, comment, order_id or None, utcnow_iso()),
        )
        await interaction.response.send_message("Merci pour votre avis !", ephemeral=True)
        config = await self.bot.db.fetchone("SELECT vouches_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if config and config["vouches_channel_id"]:
            ch = self.bot.get_channel(config["vouches_channel_id"])
            if isinstance(ch, discord.TextChannel):
                embed = tekaz_embed("⭐ Nouveau vouch", comment)
                embed.add_field(name="Auteur", value=interaction.user.mention)
                embed.add_field(name="Note", value=f"{rating}/5")
                embed.add_field(name="Order", value=order_id or "-")
                await ch.send(embed=embed)

    @vouch.command(name="stats")
    async def stats(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        rows = await self.bot.db.fetchall("SELECT rating, comment FROM vouches WHERE guild_id = ?", (interaction.guild.id,))
        if not rows:
            await interaction.response.send_message("Aucun vouch", ephemeral=True)
            return
        avg = sum(r["rating"] for r in rows) / len(rows)
        words = {}
        for r in rows:
            for w in r["comment"].lower().split():
                if len(w) < 4:
                    continue
                words[w] = words.get(w, 0) + 1
        top = sorted(words.items(), key=lambda x: x[1], reverse=True)[:5]
        top_text = ", ".join([f"{w}({c})" for w, c in top]) or "-"
        embed = tekaz_embed("Vouch Stats", f"Moyenne: **{avg:.2f}/5**\nTotal: **{len(rows)}**\nTop mots: {top_text}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VouchesCog(bot))
