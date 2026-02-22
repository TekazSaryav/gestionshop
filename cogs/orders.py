from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.constants import ORDER_STATUSES, PAYMENT_METHODS
from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_staff
from integrations.sellauth import SellAuthClient


def _map_sellauth_to_order_status(status: str) -> str:
    s = status.lower()
    if s in {"paid", "completed", "complete", "success"}:
        return "Paid"
    if s in {"refunded"}:
        return "Refunded"
    if s in {"chargeback"}:
        return "Disputed"
    if s in {"cancelled", "failed"}:
        return "Cancelled"
    return "Pending"


class OrderActionView(discord.ui.View):
    def __init__(self, cog: "OrdersCog", order_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id

    @discord.ui.button(label="✅ Mark Paid", style=discord.ButtonStyle.success)
    async def mark_paid(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.set_order_status(interaction, self.order_id, "Paid")

    @discord.ui.button(label="📦 Mark Delivered", style=discord.ButtonStyle.primary)
    async def mark_delivered(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self.cog.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (self.order_id,))
        if not row:
            await interaction.response.send_message("Commande introuvable", ephemeral=True)
            return
        ok = await self.cog.can_deliver_order(row)
        if not ok:
            await interaction.response.send_message("Livraison bloquée: paiement non confirmé (statut Paid ou vérification récente).", ephemeral=True)
            return
        await self.cog.set_order_status(interaction, self.order_id, "Delivered")

    @discord.ui.button(label="⚠️ Dispute", style=discord.ButtonStyle.secondary)
    async def dispute(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.set_order_status(interaction, self.order_id, "Disputed")

    @discord.ui.button(label="💸 Refund", style=discord.ButtonStyle.danger)
    async def refund(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.set_order_status(interaction, self.order_id, "Refunded")


class OrdersCog(commands.Cog, name="orders"):
    order = app_commands.Group(name="order", description="Gestion commandes")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sellauth = SellAuthClient()

    def _embed(self, row) -> discord.Embed:
        embed = tekaz_embed(f"🛒 Order {row['order_id']}")
        embed.add_field(name="User", value=f"<@{row['user_id']}>")
        embed.add_field(name="Product", value=row["product"])
        embed.add_field(name="Price", value=str(row["price"]))
        embed.add_field(name="Payment", value=row["payment_method"])
        embed.add_field(name="Status", value=row["status"])
        embed.add_field(name="Note", value=row["note"] or "-", inline=False)
        return embed

    async def can_deliver_order(self, order_row) -> bool:
        if order_row["status"] == "Paid":
            return True
        check = await self.bot.db.fetchone(
            "SELECT * FROM payment_checks WHERE guild_id = ? AND tkz_order_id = ? ORDER BY checked_at DESC LIMIT 1",
            (order_row["guild_id"], order_row["order_id"]),
        )
        if not check:
            return False
        try:
            checked_at = datetime.fromisoformat(check["checked_at"])
        except ValueError:
            return False
        fresh = datetime.now(timezone.utc) - checked_at <= timedelta(minutes=10)
        return fresh and check["result_status"].lower() in {"paid", "completed", "complete", "success"}

    @order.command(name="create", description="Créer une commande")
    @app_commands.checks.cooldown(3, 30)
    async def create(self, interaction: discord.Interaction, user: discord.Member, product: str, price: app_commands.Range[float, 0, None], payment: str, note: str | None = None) -> None:
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
        if status == "Delivered" and not await self.can_deliver_order(row):
            await interaction.response.send_message("Livraison bloquée: paiement non confirmé.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?", (status, utcnow_iso(), order_id))
        await self.bot.audit(row["guild_id"], interaction.user.id, "ORDER_STATUS", order_id, {"status": status})
        await interaction.response.send_message(embed=tekaz_embed("✅ Order updated", f"{order_id} → **{status}**"), ephemeral=True)

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

    @order.command(name="verify", description="Vérifier une commande via SellAuth")
    @is_staff()
    @app_commands.checks.cooldown(5, 60)
    async def verify(self, interaction: discord.Interaction, order_id: str, sellauth_order_id: str | None = None) -> None:
        assert interaction.guild
        order = await self.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        if not order:
            await interaction.response.send_message("Commande introuvable", ephemeral=True)
            return

        pay = None
        if not sellauth_order_id:
            pay = await self.bot.db.fetchone(
                "SELECT * FROM payments WHERE guild_id = ? AND tkz_order_id = ? ORDER BY updated_at DESC LIMIT 1",
                (interaction.guild.id, order_id),
            )
            sellauth_order_id = pay["sellauth_order_id"] if pay and pay["sellauth_order_id"] else None
        if not sellauth_order_id:
            await interaction.response.send_message("Fournis `sellauth_order_id` ou reçois d'abord un webhook.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            paid, status, raw = await self.sellauth.verify_paid(sellauth_order_id)
        except Exception as exc:
            await interaction.followup.send(f"Erreur SellAuth: {exc}", ephemeral=True)
            return

        mapped_status = _map_sellauth_to_order_status(status)
        await self.bot.db.execute(
            "INSERT INTO payments(guild_id, tkz_order_id, sellauth_order_id, status, amount, currency, raw_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (interaction.guild.id, order_id, sellauth_order_id, status, float(raw.get("amount") or 0), str(raw.get("currency") or ""), str(raw), utcnow_iso(), utcnow_iso()),
        )
        await self.bot.db.execute(
            "INSERT INTO payment_checks(guild_id, tkz_order_id, checked_by, result_status, raw_json, checked_at) VALUES(?,?,?,?,?,?)",
            (interaction.guild.id, order_id, interaction.user.id, status, str(raw), utcnow_iso()),
        )
        await self.bot.db.execute("UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?", (mapped_status, utcnow_iso(), order_id))
        await self.bot.audit(interaction.guild.id, interaction.user.id, "ORDER_VERIFY", order_id, {"sellauth": sellauth_order_id, "status": status})

        if paid:
            msg = f"✅ Paiement confirmé ({status}). Commande `{order_id}` marquée **Paid**."
        elif status.lower() in {"refunded", "chargeback"}:
            msg = f"⚠️ Paiement à risque ({status}). Commande `{order_id}` -> **{mapped_status}** et livraison bloquée."
        else:
            msg = f"❌ Paiement non validé ({status}). Commande conservée en **{mapped_status}**."
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OrdersCog(bot))
