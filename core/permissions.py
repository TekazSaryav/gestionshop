from __future__ import annotations

from typing import Callable

import discord
from discord import app_commands


def _has_role(member: discord.Member, role_id: int | None) -> bool:
    if not role_id:
        return False
    return any(role.id == role_id for role in member.roles)


def is_staff() -> Callable[[discord.Interaction], bool]:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        config = await interaction.client.db.fetchone("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if not config:
            return interaction.user.guild_permissions.administrator
        return _has_role(interaction.user, config["staff_role_id"]) or interaction.user.guild_permissions.administrator

    return app_commands.check(predicate)


def is_admin() -> Callable[[discord.Interaction], bool]:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        config = await interaction.client.db.fetchone("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if not config:
            return interaction.user.guild_permissions.administrator
        return _has_role(interaction.user, config["admin_role_id"]) or interaction.user.guild_permissions.administrator

    return app_commands.check(predicate)
