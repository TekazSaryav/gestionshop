from __future__ import annotations

from io import BytesIO, StringIO

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_staff


class TicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="📩 Support", style=discord.ButtonStyle.primary)
    async def support(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.open_ticket(interaction, "Support")

    @discord.ui.button(label="🧾 Order Issue", style=discord.ButtonStyle.secondary)
    async def issue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.open_ticket(interaction, "Order Issue")

    @discord.ui.button(label="🔁 Refund Request", style=discord.ButtonStyle.secondary)
    async def refund(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.open_ticket(interaction, "Refund Request")

    @discord.ui.button(label="🛡️ Report", style=discord.ButtonStyle.danger)
    async def report(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.open_ticket(interaction, "Report")


class TicketManageView(discord.ui.View):
    def __init__(self, cog: "TicketsCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.close_ticket(interaction)

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(label="📝 Transcript", style=discord.ButtonStyle.secondary)
    async def transcript(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.send_transcript(interaction)


class TicketsCog(commands.Cog, name="tickets"):
    ticket = app_commands.Group(name="ticket", description="Système de tickets")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @ticket.command(name="panel", description="Poster le panneau tickets")
    @is_staff()
    async def panel(self, interaction: discord.Interaction) -> None:
        embed = tekaz_embed("Tekaz Support", "Cliquez pour ouvrir un ticket.")
        await interaction.response.send_message(embed=embed, view=TicketView(self))

    async def open_ticket(self, interaction: discord.Interaction, category_name: str) -> None:
        assert interaction.guild
        config = await self.bot.db.fetchone("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if not config or not config["tickets_category_id"]:
            await interaction.response.send_message("Configuration tickets manquante.", ephemeral=True)
            return
        category = interaction.guild.get_channel(config["tickets_category_id"])
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Catégorie tickets invalide.", ephemeral=True)
            return
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        }
        staff_role = interaction.guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}".lower()[:90],
            category=category,
            overwrites=overwrites,
            topic=f"Tekaz ticket for {interaction.user.id} | {category_name}",
        )
        await self.bot.db.execute(
            "INSERT INTO tickets(guild_id,channel_id,user_id,category,status,created_at) VALUES(?,?,?,?,?,?)",
            (interaction.guild.id, channel.id, interaction.user.id, category_name, "Open", utcnow_iso()),
        )
        await self.bot.audit(interaction.guild.id, interaction.user.id, "TICKET_OPEN", str(channel.id), {"category": category_name})
        await channel.send(embed=tekaz_embed("📩 Ticket ouvert", f"Catégorie: **{category_name}**"), view=TicketManageView(self))
        await interaction.response.send_message(f"Ticket créé: {channel.mention}", ephemeral=True)

    async def _get_ticket(self, channel_id: int):
        return await self.bot.db.fetchone("SELECT * FROM tickets WHERE channel_id = ? AND status = 'Open'", (channel_id,))

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        ticket = await self._get_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("Ticket introuvable.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (interaction.user.id, interaction.channel_id))
        await self.bot.audit(ticket["guild_id"], interaction.user.id, "TICKET_CLAIM", str(interaction.channel_id))
        await interaction.response.send_message(f"Ticket claim par {interaction.user.mention}")

    async def send_transcript(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Salon invalide", ephemeral=True)
            return
        output = StringIO()
        async for msg in channel.history(limit=200, oldest_first=True):
            output.write(f"[{msg.created_at}] {msg.author} : {msg.content}\n")
        content = output.getvalue() or "Transcript vide"
        file = discord.File(BytesIO(content.encode("utf-8")), filename=f"transcript-{channel.id}.txt")
        await interaction.response.send_message("Transcript prêt.", file=file, ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        ticket = await self._get_ticket(interaction.channel_id)
        if not ticket or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Ticket introuvable.", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE tickets SET status = 'Closed', closed_at = ? WHERE channel_id = ?", (utcnow_iso(), interaction.channel_id)
        )
        await self.bot.audit(ticket["guild_id"], interaction.user.id, "TICKET_CLOSE", str(interaction.channel_id))
        await interaction.response.send_message("Ticket fermé. Archivage...")
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}", locked=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
