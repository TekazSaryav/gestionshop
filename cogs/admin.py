from __future__ import annotations

import os
import shutil
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.helpers import tekaz_embed, utcnow_iso
from core.permissions import is_admin, is_staff

CONFIG_KEYS = {
    "sellauth_api_key": "TEXT",
    "sellauth_store_id": "TEXT",
}


class AdminCog(commands.Cog, name="admin"):
    config = app_commands.Group(name="config", description="Configuration Tekaz")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Configurer Tekaz Shop")
    @is_admin()
    async def setup(
        self,
        interaction: discord.Interaction,
        staff_role: discord.Role,
        admin_role: discord.Role,
        tickets_category: discord.CategoryChannel,
        orders_channel: discord.TextChannel,
        proofs_channel: discord.TextChannel,
        logs_channel: discord.TextChannel,
        vouches_channel: discord.TextChannel,
    ) -> None:
        assert interaction.guild
        now = utcnow_iso()
        await self.bot.db.execute(
            """
            INSERT INTO config(guild_id, staff_role_id, admin_role_id, tickets_category_id, orders_channel_id, proofs_channel_id, logs_channel_id, vouches_channel_id, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
            staff_role_id=excluded.staff_role_id, admin_role_id=excluded.admin_role_id,
            tickets_category_id=excluded.tickets_category_id, orders_channel_id=excluded.orders_channel_id,
            proofs_channel_id=excluded.proofs_channel_id, logs_channel_id=excluded.logs_channel_id,
            vouches_channel_id=excluded.vouches_channel_id, updated_at=excluded.updated_at
            """,
            (interaction.guild.id, staff_role.id, admin_role.id, tickets_category.id, orders_channel.id, proofs_channel.id, logs_channel.id, vouches_channel.id, now, now),
        )
        await self.bot.audit(interaction.guild.id, interaction.user.id, "CONFIG_SETUP", str(interaction.guild.id), {"staff_role": staff_role.id})
        await interaction.response.send_message(embed=tekaz_embed("✅ Setup done", "Configuration enregistrée."), ephemeral=True)

    @config.command(name="set", description="Définir une valeur de config")
    @is_admin()
    async def config_set(self, interaction: discord.Interaction, key: str, value: str) -> None:
        assert interaction.guild
        if key not in CONFIG_KEYS:
            await interaction.response.send_message(f"Clé invalide. Clés: {', '.join(CONFIG_KEYS)}", ephemeral=True)
            return
        now = utcnow_iso()
        await self.bot.db.execute(
            f"INSERT INTO config(guild_id, {key}, created_at, updated_at) VALUES(?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET {key}=excluded.{key}, updated_at=excluded.updated_at",
            (interaction.guild.id, value, now, now),
        )
        if key == "sellauth_api_key":
            os.environ["SELLAUTH_API_KEY"] = value
        if key == "sellauth_store_id":
            os.environ["SELLAUTH_STORE_ID"] = value
        await self.bot.audit(interaction.guild.id, interaction.user.id, "CONFIG_SET", key)
        await interaction.response.send_message(embed=tekaz_embed("✅ Config set", f"`{key}` mis à jour."), ephemeral=True)

    @config_set.autocomplete("key")
    async def config_key_autocomplete(self, _: discord.Interaction, current: str):
        return [app_commands.Choice(name=k, value=k) for k in CONFIG_KEYS if current.lower() in k.lower()]

    @config.command(name="show", description="Afficher la configuration")
    @is_staff()
    async def config_show(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        row = await self.bot.db.fetchone("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if not row:
            await interaction.response.send_message(embed=tekaz_embed("❌ Missing config", "Lancez /setup."), ephemeral=True)
            return
        embed = tekaz_embed("Tekaz Config")
        keys = ["staff_role_id", "admin_role_id", "tickets_category_id", "orders_channel_id", "proofs_channel_id", "logs_channel_id", "vouches_channel_id", "sellauth_store_id", "sellauth_api_key"]
        for key in keys:
            value = row[key]
            if key == "sellauth_api_key" and value:
                value = "****"
            embed.add_field(name=key, value=str(value or "-"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="backup_db", description="Créer une copie de la base de données")
    @is_staff()
    async def backup_db(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db_path = Path(self.bot.db.path)
        out = db_path.with_suffix(".backup.sqlite")
        shutil.copy2(db_path, out)
        await interaction.followup.send(embed=tekaz_embed("✅ Backup DB", f"Backup créé: `{out}`"), ephemeral=True)

    @app_commands.command(name="health", description="Santé du bot")
    async def health(self, interaction: discord.Interaction) -> None:
        db_size = Path(self.bot.db.path).stat().st_size if Path(self.bot.db.path).exists() else 0
        embed = tekaz_embed("Tekaz Health")
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms")
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)))
        embed.add_field(name="DB size", value=f"{db_size} bytes")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
