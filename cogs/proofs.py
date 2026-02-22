from __future__ import annotations

import json
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.constants import DANGEROUS_FILE_EXTENSIONS, PROOF_STATUSES, PROOF_TYPES
from core.helpers import parse_json, tekaz_embed, utcnow_iso
from core.permissions import is_staff


class ProofSubmitModal(discord.ui.Modal, title="Submit Proof"):
    order_id = discord.ui.TextInput(label="order_id", required=True, max_length=32)
    proof_type = discord.ui.TextInput(label="type", required=True, placeholder="Delivery proof / Payment proof / Issue proof / Other")
    description = discord.ui.TextInput(label="description", required=True, style=discord.TextStyle.paragraph, max_length=1000)
    links = discord.ui.TextInput(label="links", required=False, style=discord.TextStyle.paragraph)

    def __init__(self, cog: "ProofsCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_proof_submission(interaction, str(self.order_id), str(self.proof_type), str(self.description), str(self.links))


class ProofActionView(discord.ui.View):
    def __init__(self, cog: "ProofsCog", proof_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.proof_id = proof_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.set_proof_status(interaction, self.proof_id, "Approved")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.set_proof_status(interaction, self.proof_id, "Rejected")

    @discord.ui.button(label="🧷 Attach to Order", style=discord.ButtonStyle.secondary)
    async def attach(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("Preuve déjà liée à la commande via order_id.", ephemeral=True)

    @discord.ui.button(label="🗂️ Export JSON", style=discord.ButtonStyle.primary)
    async def export(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self.cog.bot.db.fetchone("SELECT * FROM proofs WHERE proof_id = ?", (self.proof_id,))
        if not row:
            await interaction.response.send_message("Introuvable", ephemeral=True)
            return
        payload = json.dumps(dict(row), ensure_ascii=False, indent=2)
        file = discord.File(fp=discord.utils.MISSING, filename="proof.json")
        from io import BytesIO

        file = discord.File(BytesIO(payload.encode("utf-8")), filename=f"{self.proof_id}.json")
        await interaction.response.send_message(file=file, ephemeral=True)


class ProofsCog(commands.Cog, name="proofs"):
    proof = app_commands.Group(name="proof", description="Gestion des preuves")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.max_attachments = int(os.getenv("MAX_PROOF_ATTACHMENTS", "5"))

    @proof.command(name="submit", description="Soumettre une preuve")
    @app_commands.checks.cooldown(1, 60)
    async def submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ProofSubmitModal(self))

    async def handle_proof_submission(
        self,
        interaction: discord.Interaction,
        order_id: str,
        proof_type: str,
        description: str,
        links: str,
    ) -> None:
        if proof_type not in PROOF_TYPES:
            await interaction.response.send_message("Type invalide.", ephemeral=True)
            return
        await interaction.response.send_message("Upload vos pièces jointes dans les 60 secondes dans ce salon.", ephemeral=True)

        def check(m: discord.Message) -> bool:
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id

        attachments = []
        try:
            msg = await self.bot.wait_for("message", timeout=60, check=check)
            if len(msg.attachments) > self.max_attachments:
                await interaction.followup.send(f"Max {self.max_attachments} fichiers.", ephemeral=True)
                return
            for a in msg.attachments:
                ext = Path(a.filename).suffix.lower()
                if ext in DANGEROUS_FILE_EXTENSIONS:
                    continue
                attachments.append(a.url)
        except TimeoutError:
            pass

        proof_id = await self.bot.next_proof_id()
        links_list = [x.strip() for x in links.split() if x.strip()]
        now = utcnow_iso()
        assert interaction.guild
        await self.bot.db.execute(
            "INSERT INTO proofs(proof_id,guild_id,order_id,user_id,type,description,links_json,attachments_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                proof_id,
                interaction.guild.id,
                order_id,
                interaction.user.id,
                proof_type,
                description,
                json.dumps(links_list),
                json.dumps(attachments),
                "Pending",
                now,
                now,
            ),
        )
        await self.bot.audit(interaction.guild.id, interaction.user.id, "PROOF_SUBMIT", proof_id, {"order_id": order_id})
        await interaction.followup.send(embed=tekaz_embed("✅ Proof submitted", f"ID: `{proof_id}`"), ephemeral=True)

        config = await self.bot.db.fetchone("SELECT proofs_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if config and config["proofs_channel_id"]:
            ch = self.bot.get_channel(config["proofs_channel_id"])
            if isinstance(ch, discord.TextChannel):
                embed = tekaz_embed(f"📦 Proof {proof_id}", description)
                embed.add_field(name="Order", value=order_id)
                embed.add_field(name="Type", value=proof_type)
                embed.add_field(name="User", value=interaction.user.mention)
                embed.add_field(name="Links", value="\n".join(links_list) or "-", inline=False)
                embed.add_field(name="Attachments", value="\n".join(attachments) or "-", inline=False)
                if attachments:
                    embed.set_thumbnail(url=attachments[0])
                await ch.send(embed=embed, view=ProofActionView(self, proof_id))

    async def set_proof_status(self, interaction: discord.Interaction, proof_id: str, status: str) -> None:
        if status not in PROOF_STATUSES:
            await interaction.response.send_message("Status invalide", ephemeral=True)
            return
        row = await self.bot.db.fetchone("SELECT * FROM proofs WHERE proof_id = ?", (proof_id,))
        if not row:
            await interaction.response.send_message("Preuve introuvable", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE proofs SET status = ?, staff_id = ?, updated_at = ? WHERE proof_id = ?",
            (status, interaction.user.id, utcnow_iso(), proof_id),
        )
        await self.bot.audit(row["guild_id"], interaction.user.id, "PROOF_STATUS", proof_id, {"status": status})
        await interaction.response.send_message(embed=tekaz_embed("Proof updated", f"{proof_id} -> {status}"), ephemeral=True)

    @proof.command(name="view", description="Voir un dossier preuve")
    async def view(self, interaction: discord.Interaction, proof_id: str) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM proofs WHERE proof_id = ?", (proof_id,))
        if not row:
            await interaction.response.send_message("Introuvable", ephemeral=True)
            return
        if interaction.user.id != row["user_id"]:
            config = await self.bot.db.fetchone("SELECT staff_role_id FROM config WHERE guild_id = ?", (row["guild_id"],))
            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
            if not (member and config and any(r.id == config["staff_role_id"] for r in member.roles)):
                await interaction.response.send_message("Accès refusé", ephemeral=True)
                return
        embed = tekaz_embed(f"Proof {proof_id}", row["description"])
        embed.add_field(name="Order", value=row["order_id"])
        embed.add_field(name="Status", value=row["status"])
        embed.add_field(name="Links", value="\n".join(parse_json(row["links_json"], [])) or "-")
        embed.add_field(name="Attachments", value="\n".join(parse_json(row["attachments_json"], [])) or "-", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @proof.command(name="list", description="Lister les preuves par commande")
    async def list_proofs(self, interaction: discord.Interaction, order_id: str) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM proofs WHERE order_id = ? ORDER BY created_at DESC", (order_id,))
        if not rows:
            await interaction.response.send_message("Aucune preuve.", ephemeral=True)
            return
        text = "\n".join([f"`{r['proof_id']}` • <@{r['user_id']}> • **{r['status']}**" for r in rows[:20]])
        await interaction.response.send_message(embed=tekaz_embed(f"Proofs {order_id}", text), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProofsCog(bot))
