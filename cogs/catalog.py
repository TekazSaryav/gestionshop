from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_staff


@dataclass(frozen=True)
class MenuCategory:
    key: str
    label: str
    channel_name: str
    products: tuple[str, ...]


MENU_CATEGORIES: tuple[MenuCategory, ...] = (
    MenuCategory(
        key="accounts",
        label="Accounts",
        channel_name="accounts",
        products=(
            "Netflix",
            "Spotify",
            "Crunchyroll",
            "Disney+",
            "Youtube",
            "ChatGPT+",
            "Prime Video",
            "Canal+",
            "Paramount+",
            "Canva",
            "Xbox GamePass Ultimate",
            "CapCut",
            "HBO Max",
            "DAZN",
        ),
    ),
    MenuCategory(
        key="cheat",
        label="Cheat",
        channel_name="cheat",
        products=(
            "Unlock All Valo",
            "Ravage Valo",
            "VIP Valo",
            "One Click Spoofer Valo",
            "Bundle Valo",
        ),
    ),
    MenuCategory(
        key="boosts",
        label="Boosts",
        channel_name="boosts",
        products=("Server Boosts", "TikTok Boosts", "Instagram Boosts"),
    ),
    MenuCategory(
        key="vpn",
        label="VPN",
        channel_name="vpn",
        products=("Mullvad VPN", "NordVPN", "CyberGhost VPN", "Express VPN", "IpVanish"),
    ),
    MenuCategory(
        key="tools",
        label="Tools",
        channel_name="tools",
        products=("Booster Tool", "Permanant Spoofer", "One Click Spoofer"),
    ),
    MenuCategory(
        key="formations",
        label="Formations",
        channel_name="formation",
        products=(
            "OnlyScale - Anthony Sirius",
            "AlphaGold - LaMenace",
            "Yomi - Success Pro Elite V2",
            "Marcus - King Of Shopify V2",
        ),
    ),
)
MENU_BY_KEY = {c.key: c for c in MENU_CATEGORIES}


class ProductSelect(discord.ui.Select):
    def __init__(self, cog: "CatalogCog", category: MenuCategory) -> None:
        options = [discord.SelectOption(label=name, value=name) for name in category.products]
        super().__init__(
            custom_id=f"catalog:{category.key}",
            placeholder=f"Choisis une offre ({category.label})",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        value = self.values[0]
        await self.cog.save_selection(interaction, self.category, value)
        await interaction.response.send_message(
            embed=tekaz_embed("✅ Choix enregistré", f"**{self.category.label}** → `{value}`"),
            ephemeral=True,
        )


class ProductMenuView(discord.ui.View):
    def __init__(self, cog: "CatalogCog", category: MenuCategory) -> None:
        super().__init__(timeout=None)
        self.add_item(ProductSelect(cog, category))


class CatalogCog(commands.Cog, name="catalog"):
    catalog = app_commands.Group(name="catalog", description="Menus produits")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        for category in MENU_CATEGORIES:
            self.bot.add_view(ProductMenuView(self, category))

    async def save_selection(self, interaction: discord.Interaction, category: MenuCategory, selected_item: str) -> None:
        assert interaction.guild
        now = utcnow_iso()
        await self.bot.db.execute(
            "INSERT INTO menu_selections(guild_id, user_id, category, item, channel_id, message_id, selected_at) VALUES(?,?,?,?,?,?,?)",
            (
                interaction.guild.id,
                interaction.user.id,
                category.key,
                selected_item,
                interaction.channel_id,
                interaction.message.id if interaction.message else None,
                now,
            ),
        )
        await self.bot.db.execute(
            """
            INSERT INTO menu_state(guild_id, user_id, category, last_item, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(guild_id, user_id, category)
            DO UPDATE SET last_item=excluded.last_item, updated_at=excluded.updated_at
            """,
            (interaction.guild.id, interaction.user.id, category.key, selected_item, now),
        )
        await self.bot.audit(
            interaction.guild.id,
            interaction.user.id,
            "CATALOG_SELECT",
            f"{category.key}:{selected_item}",
            {"channel_id": interaction.channel_id},
        )

    def panel_embed(self, category: MenuCategory) -> discord.Embed:
        lines = "\n".join(f"• {item}" for item in category.products)
        return tekaz_embed(
            f"🛍️ {category.label}",
            f"Choisis un produit dans le menu déroulant ci-dessous.\n\n{lines}",
        )

    @catalog.command(name="setup", description="Publier tous les menus déroulants dans leurs salons")
    @is_staff()
    async def setup_panels(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        await interaction.response.defer(ephemeral=True)

        created: list[str] = []
        missing: list[str] = []
        for category in MENU_CATEGORIES:
            channel = discord.utils.get(interaction.guild.text_channels, name=category.channel_name)
            if not channel:
                missing.append(f"{category.label} -> #{category.channel_name}")
                continue

            view = ProductMenuView(self, category)
            message = await channel.send(embed=self.panel_embed(category), view=view)
            await self.bot.db.execute(
                """
                INSERT INTO menu_panels(guild_id, category, channel_id, message_id, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(guild_id, category)
                DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, updated_at=excluded.updated_at
                """,
                (interaction.guild.id, category.key, channel.id, message.id, utcnow_iso()),
            )
            created.append(f"{category.label}: {channel.mention}")

        body = "\n".join(f"✅ {line}" for line in created) if created else "Aucun panel créé."
        if missing:
            body += "\n\n" + "\n".join(f"⚠️ Salon introuvable: {line}" for line in missing)
        await interaction.followup.send(embed=tekaz_embed("Setup menus", body), ephemeral=True)

    @catalog.command(name="my", description="Voir tes derniers choix dans les menus")
    async def my_choices(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        rows = await self.bot.db.fetchall(
            "SELECT category, last_item, updated_at FROM menu_state WHERE guild_id = ? AND user_id = ? ORDER BY updated_at DESC",
            (interaction.guild.id, interaction.user.id),
        )
        if not rows:
            await interaction.response.send_message("Tu n'as encore fait aucun choix.", ephemeral=True)
            return

        lines = []
        for row in rows:
            category = MENU_BY_KEY.get(row["category"])
            category_name = category.label if category else row["category"]
            lines.append(f"**{category_name}**: {row['last_item']}\n`{row['updated_at']}`")
        await interaction.response.send_message(embed=tekaz_embed("🧠 Tes choix sauvegardés", "\n\n".join(lines)), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CatalogCog(bot))
