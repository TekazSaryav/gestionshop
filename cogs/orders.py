from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.constants import ORDER_STATUSES, PAYMENT_METHODS
from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_staff


class OrderActionView(discord.ui.View):
    def __init__(self, cog: "OrdersCog", order_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id

    async def _set(self, interaction: discord.Interaction, status: str) -> None:
        await self.cog.set_order_status(interaction, self.order_id, status)

    @discord.ui.button(label="✅ Mark Paid", style=discord.ButtonStyle.success)
    async def mark_paid(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._set(interaction, "Paid")

    @discord.ui.button(label="📦 Mark Delivered", style=discord.ButtonStyle.primary)
    async def mark_delivered(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._set(interaction, "Delivered")

    @discord.ui.button(label="⚠️ Dispute", style=discord.ButtonStyle.secondary)
    async def dispute(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._set(interaction, "Disputed")

    @discord.ui.button(label="💸 Refund", style=discord.ButtonStyle.danger)
    async def refund(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._set(interaction, "Refunded")


class OrdersCog(commands.Cog, name="orders"):
    order = app_commands.Group(name="order", description="Gestion commandes")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _embed(self, row: dict | discord.utils.MISSING) -> discord.Embed:
        embed = tekaz_embed(f"🛒 Order {row['order_id']}")
        embed.add_field(name="User", value=f"<@{row['user_id']}>")
        embed.add_field(name="Product", value=row["product"])
        embed.add_field(name="Price", value=str(row["price"]))
        embed.add_field(name="Payment", value=row["payment_method"])
        embed.add_field(name="Status", value=row["status"])
        embed.add_field(name="Note", value=row["note"] or "-", inline=False)
        return embed

    @order.command(name="create", description="Créer une commande")
    @app_commands.describe(note="Optionnel")
    @app_commands.checks.cooldown(3, 30)
    async def create(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        product: str,
        price: app_commands.Range[float, 0, None],
        payment: str,
        note: str | None = None,
    ) -> None:
        assert interaction.guild
        if payment not in PAYMENT_METHODS:
            await interaction.response.send_message("Méthode de paiement invalide", ephemeral=True)
            return
        order_id = await self.bot.next_order_id(interaction.guild.id)
        now = utcnow_iso()
        await self.bot.db.execute(
            "INSERT INTO orders(order_id,guild_id,user_id,product,price,payment_method,status,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (order_id, interaction.guild.id, user.id, product, price, payment, "Pending", note, now, now),
        )
        await self.bot.audit(interaction.guild.id, interaction.user.id, "ORDER_CREATE", order_id, {"price": price})
        row = await self.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        embed = self._embed(row)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        config = await self.bot.db.fetchone("SELECT orders_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if config and config["orders_channel_id"]:
            channel = self.bot.get_channel(config["orders_channel_id"])
            if isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed, view=OrderActionView(self, order_id))

    @create.autocomplete("payment")
    async def payment_autocomplete(self, _: discord.Interaction, current: str):
        return [app_commands.Choice(name=m, value=m) for m in PAYMENT_METHODS if current.lower() in m.lower()]

    @order.command(name="status", description="Voir statut commande")
    async def status(self, interaction: discord.Interaction, order_id: str) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        if not row:
            await interaction.response.send_message(embed=tekaz_embed("❌ Introuvable", "Commande inexistante."), ephemeral=True)
            return
        await interaction.response.send_message(embed=self._embed(row), ephemeral=True)

    async def set_order_status(self, interaction: discord.Interaction, order_id: str, status: str) -> None:
        if status not in ORDER_STATUSES:
            await interaction.response.send_message("Status invalide", ephemeral=True)
            return
        row = await self.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        if not row:
            await interaction.response.send_message("Commande introuvable", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?", (status, utcnow_iso(), order_id))
        await self.bot.audit(row["guild_id"], interaction.user.id, "ORDER_STATUS", order_id, {"status": status})
        embed = tekaz_embed("✅ Order updated", f"{order_id} → **{status}**")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @order.command(name="setstatus", description="Modifier statut")
    @is_staff()
    async def setstatus(self, interaction: discord.Interaction, order_id: str, status: str) -> None:
        await self.set_order_status(interaction, order_id, status)

    @setstatus.autocomplete("status")
    async def status_autocomplete(self, _: discord.Interaction, current: str):
        return [app_commands.Choice(name=s, value=s) for s in ORDER_STATUSES if current.lower() in s.lower()]

    @order.command(name="list", description="Lister les commandes")
    @is_staff()
    async def list_orders(self, interaction: discord.Interaction, user: discord.Member | None = None, status: str | None = None) -> None:
        assert interaction.guild
        q = "SELECT * FROM orders WHERE guild_id = ?"
        params: list = [interaction.guild.id]
        if user:
            q += " AND user_id = ?"
            params.append(user.id)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT 20"
        rows = await self.bot.db.fetchall(q, tuple(params))
        if not rows:
            await interaction.response.send_message("Aucune commande.", ephemeral=True)
            return
        lines = [f"`{r['order_id']}` • <@{r['user_id']}> • **{r['status']}** • {r['product']}" for r in rows]
        await interaction.response.send_message(embed=tekaz_embed("Orders", "\n".join(lines)), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OrdersCog(bot))
