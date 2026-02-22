from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.constants import STOCK_MODES
from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_staff


class StockCog(commands.Cog, name="stock"):
    product = app_commands.Group(name="product", description="Produits")
    stock = app_commands.Group(name="stock", description="Stock")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @product.command(name="add")
    @is_staff()
    async def add_product(self, interaction: discord.Interaction, name: str, price: float, description: str, stock_mode: str) -> None:
        if stock_mode not in STOCK_MODES:
            await interaction.response.send_message("Mode invalide", ephemeral=True)
            return
        assert interaction.guild
        now = utcnow_iso()
        await self.bot.db.execute(
            "INSERT INTO products(guild_id,name,price,description,stock_mode,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (interaction.guild.id, name, price, description, stock_mode, now, now),
        )
        await interaction.response.send_message(embed=tekaz_embed("✅ Product added", name), ephemeral=True)

    @product.command(name="edit")
    @is_staff()
    async def edit_product(self, interaction: discord.Interaction, product_id: int, name: str | None = None, price: float | None = None, description: str | None = None) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM products WHERE product_id = ?", (product_id,))
        if not row:
            await interaction.response.send_message("Produit introuvable", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE products SET name=?, price=?, description=?, updated_at=? WHERE product_id=?",
            (name or row["name"], price if price is not None else row["price"], description or row["description"], utcnow_iso(), product_id),
        )
        await interaction.response.send_message("Produit mis à jour", ephemeral=True)

    @product.command(name="remove")
    @is_staff()
    async def remove_product(self, interaction: discord.Interaction, product_id: int) -> None:
        await self.bot.db.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
        await interaction.response.send_message("Produit supprimé", ephemeral=True)

    @product.command(name="list")
    async def list_product(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        rows = await self.bot.db.fetchall("SELECT * FROM products WHERE guild_id = ? ORDER BY product_id DESC", (interaction.guild.id,))
        desc = "\n".join([f"`#{r['product_id']}` {r['name']} • {r['price']} • {r['stock_mode']}" for r in rows]) or "Aucun produit"
        await interaction.response.send_message(embed=tekaz_embed("📦 Produits", desc), ephemeral=True)

    @stock.command(name="add")
    @is_staff()
    async def add_keys(self, interaction: discord.Interaction, product_id: int, keys: str) -> None:
        assert interaction.guild
        values = [k.strip() for k in keys.splitlines() if k.strip()]
        for key in values:
            await self.bot.db.execute(
                "INSERT INTO stock_keys(guild_id,product_id,key_value,is_used) VALUES(?,?,?,0)", (interaction.guild.id, product_id, key)
            )
        await interaction.response.send_message(f"{len(values)} clés ajoutées.", ephemeral=True)

    @stock.command(name="view")
    @is_staff()
    async def view_stock(self, interaction: discord.Interaction, product_id: int) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT key_value FROM stock_keys WHERE product_id = ? AND is_used = 0 LIMIT 20", (product_id,)
        )
        masked = [f"{r['key_value'][:4]}****{r['key_value'][-4:]}" for r in rows]
        await interaction.response.send_message(embed=tekaz_embed("Stock Keys", "\n".join(masked) or "Vide"), ephemeral=True)

    @stock.command(name="deliver")
    @is_staff()
    async def deliver(self, interaction: discord.Interaction, order_id: str) -> None:
        order = await self.bot.db.fetchone("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        if not order:
            await interaction.response.send_message("Commande introuvable", ephemeral=True)
            return
        orders_cog = self.bot.get_cog("orders")
        if orders_cog and not await orders_cog.can_deliver_order(order):
            await interaction.response.send_message("Livraison bloquée: paiement non confirmé (Paid ou check SellAuth < 10 min).", ephemeral=True)
            return
        product = await self.bot.db.fetchone("SELECT * FROM products WHERE name = ? AND guild_id = ?", (order["product"], order["guild_id"]))
        if not product or product["stock_mode"] != "KeyStock":
            await interaction.response.send_message("Produit non KeyStock", ephemeral=True)
            return
        key = await self.bot.db.fetchone(
            "SELECT * FROM stock_keys WHERE guild_id = ? AND product_id = ? AND is_used = 0 LIMIT 1", (order["guild_id"], product["product_id"])
        )
        if not key:
            await interaction.response.send_message("Stock vide", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE stock_keys SET is_used=1, used_at=?, order_id=? WHERE id=?", (utcnow_iso(), order_id, key["id"]))
        await self.bot.db.execute("UPDATE orders SET status='Delivered', updated_at=? WHERE order_id=?", (utcnow_iso(), order_id))
        user = interaction.guild.get_member(order["user_id"])
        if user:
            try:
                await user.send(embed=tekaz_embed("✅ Delivery", f"Commande {order_id}\nClé: `{key['key_value']}`"))
            except discord.HTTPException:
                pass
        await interaction.response.send_message(embed=tekaz_embed("Delivered", f"Commande {order_id} livrée."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StockCog(bot))
