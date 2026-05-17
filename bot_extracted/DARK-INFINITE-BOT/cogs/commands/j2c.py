import discord
from discord.ext import commands
from discord import ui, SelectOption
import aiosqlite
import asyncio
from typing import Dict, List, Optional

CATEGORY_NAME = "temp voice"
INTERFACE_CHANNEL = "✨ voice-interface"
JOIN_CHANNEL = "➕ JOIN TO CREATE"
DB_PATH = "j2c_data.db"


class JoinToCreate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.private_channels: Dict[int, Dict] = {}
        self.setup_data: Dict[int, Dict] = {}
        self.blocked_users: Dict[int, List[int]] = {}
        self.trusted_users: Dict[int, List[int]] = {}

    async def init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_setup (
                    guild_id INTEGER PRIMARY KEY,
                    join_channel_id INTEGER,
                    control_channel_id INTEGER,
                    control_message_id INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS private_channels (
                    vc_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    owner_id INTEGER,
                    member_limit INTEGER DEFAULT 0,
                    region TEXT DEFAULT '',
                    is_locked BOOLEAN DEFAULT FALSE,
                    has_waiting_room BOOLEAN DEFAULT FALSE,
                    chat_channel_id INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS blocked_users (
                    vc_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (vc_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trusted_users (
                    vc_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (vc_id, user_id)
                )
            """)
            await db.commit()

    async def load_data(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM guild_setup") as cursor:
                async for row in cursor:
                    guild_id, join_channel_id, control_channel_id, control_message_id = row
                    self.setup_data[guild_id] = {
                        "join_channel_id": join_channel_id,
                        "control_channel_id": control_channel_id,
                        "control_message_id": control_message_id
                    }

            async with db.execute("SELECT * FROM private_channels") as cursor:
                async for row in cursor:
                    vc_id, guild_id, owner_id, member_limit, region, is_locked, has_waiting_room, chat_channel_id = row
                    self.private_channels[vc_id] = {
                        "owner": owner_id,
                        "limit": member_limit,
                        "region": region,
                        "is_locked": bool(is_locked),
                        "has_waiting_room": bool(has_waiting_room),
                        "chat_channel_id": chat_channel_id or 0,
                        "guild_id": guild_id
                    }

            async with db.execute("SELECT * FROM blocked_users") as cursor:
                async for row in cursor:
                    vc_id, user_id = row
                    self.blocked_users.setdefault(vc_id, []).append(user_id)

            async with db.execute("SELECT * FROM trusted_users") as cursor:
                async for row in cursor:
                    vc_id, user_id = row
                    self.trusted_users.setdefault(vc_id, []).append(user_id)

    async def save_guild_setup(self, guild_id: int, data: Dict):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO guild_setup
                (guild_id, join_channel_id, control_channel_id, control_message_id)
                VALUES (?, ?, ?, ?)
            """, (guild_id, data["join_channel_id"], data["control_channel_id"], data["control_message_id"]))
            await db.commit()

    async def save_private_channel(self, vc_id: int, guild_id: int, data: Dict):
        try:
            self.private_channels[vc_id] = data
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO private_channels
                    (vc_id, guild_id, owner_id, member_limit, region, is_locked, has_waiting_room, chat_channel_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    vc_id, guild_id,
                    data["owner"],
                    data.get("limit", 0),
                    data.get("region", ""),
                    data.get("is_locked", False),
                    data.get("has_waiting_room", False),
                    data.get("chat_channel_id", 0)
                ))
                await db.commit()
        except Exception as e:
            print(f"[TempVoice] Error saving channel: {e}")

    async def delete_private_channel(self, vc_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM private_channels WHERE vc_id = ?", (vc_id,))
            await db.execute("DELETE FROM blocked_users WHERE vc_id = ?", (vc_id,))
            await db.execute("DELETE FROM trusted_users WHERE vc_id = ?", (vc_id,))
            await db.commit()
        self.blocked_users.pop(vc_id, None)
        self.trusted_users.pop(vc_id, None)

    async def delete_guild_setup(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM guild_setup WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM private_channels WHERE guild_id = ?", (guild_id,))
            await db.commit()

    async def trust_user(self, vc_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO trusted_users (vc_id, user_id) VALUES (?, ?)", (vc_id, user_id))
            await db.commit()
        self.trusted_users.setdefault(vc_id, [])
        if user_id not in self.trusted_users[vc_id]:
            self.trusted_users[vc_id].append(user_id)

    async def untrust_user(self, vc_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM trusted_users WHERE vc_id = ? AND user_id = ?", (vc_id, user_id))
            await db.commit()
        if vc_id in self.trusted_users and user_id in self.trusted_users[vc_id]:
            self.trusted_users[vc_id].remove(user_id)

    async def block_user(self, vc_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO blocked_users (vc_id, user_id) VALUES (?, ?)", (vc_id, user_id))
            await db.commit()
        self.blocked_users.setdefault(vc_id, [])
        if user_id not in self.blocked_users[vc_id]:
            self.blocked_users[vc_id].append(user_id)

    async def unblock_user(self, vc_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM blocked_users WHERE vc_id = ? AND user_id = ?", (vc_id, user_id))
            await db.commit()
        if vc_id in self.blocked_users and user_id in self.blocked_users[vc_id]:
            self.blocked_users[vc_id].remove(user_id)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.init_db()
        await self.load_data()
        for guild_id, data in self.setup_data.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            try:
                control_channel = guild.get_channel(data["control_channel_id"])
                if control_channel and data["control_message_id"]:
                    try:
                        message = await control_channel.fetch_message(data["control_message_id"])
                        await message.edit(view=TempVoiceView(self))
                    except Exception:
                        embed = self.create_interface_embed()
                        msg = await control_channel.send(embed=embed, view=TempVoiceView(self))
                        self.setup_data[guild_id]["control_message_id"] = msg.id
                        await self.save_guild_setup(guild_id, self.setup_data[guild_id])
            except Exception:
                continue

    def create_interface_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="TempVoice Interface",
            description=(
                "This **interface** can be used to manage temporary voice channels.\n"
                "More options are available with **>voice** commands.\n\n"
                "**ᴄᴅ NAME** ‎ ‎ ‎ **👥 LIMIT** ‎ ‎ ‎ **🛡 PRIVACY** ‎ ‎ ‎ **⏳ WAITING ROOM** ‎ ‎ ‎ **💬 CHAT**\n"
                "**👤 TRUST** ‎ ‎ ‎ **🚫 UNTRUST** ‎ ‎ ‎ **📞 INVITE** ‎ ‎ ‎ **👢 KICK** ‎ ‎ ‎ **🌍 REGION**\n"
                "**🚷 BLOCK** ‎ ‎ ‎ **🔓 UNBLOCK** ‎ ‎ ‎ **👑 CLAIM** ‎ ‎ ‎ **🔄 TRANSFER** ‎ ‎ ‎ **🗑 DELETE**\n\n"
                "Press the buttons below to use the interface"
            ),
            color=0x2b2d31
        )
        return embed

    @commands.command(name='tempvoice', aliases=['tvsetup', 'j2csetup'])
    @commands.has_permissions(administrator=True)
    async def setup_tempvoice(self, ctx):
        if ctx.guild.id in self.setup_data:
            await ctx.send("❌ TempVoice is already set up in this server! Use `>tempvoice reset` to reset it.")
            return

        msg = await ctx.send("<a:loading:1504060522516054127> Setting up TempVoice system...")

        category = discord.utils.get(ctx.guild.categories, name=CATEGORY_NAME)
        if not category:
            category = await ctx.guild.create_category(CATEGORY_NAME)

        join_channel = await ctx.guild.create_voice_channel(JOIN_CHANNEL, category=category)

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False, add_reactions=False),
            ctx.guild.me: discord.PermissionOverwrite(send_messages=True, manage_messages=True)
        }
        control_channel = await ctx.guild.create_text_channel(
            INTERFACE_CHANNEL, category=category, overwrites=overwrites
        )

        embed = self.create_interface_embed()
        view = TempVoiceView(self)
        control_message = await control_channel.send(embed=embed, view=view)

        self.setup_data[ctx.guild.id] = {
            "join_channel_id": join_channel.id,
            "control_channel_id": control_channel.id,
            "control_message_id": control_message.id
        }
        await self.save_guild_setup(ctx.guild.id, self.setup_data[ctx.guild.id])

        embed2 = discord.Embed(
            title="✅ TempVoice Setup Complete",
            description=(
                f"**Interface Channel:** {control_channel.mention}\n"
                f"**Join Channel:** {join_channel.mention}\n\n"
                f"Members can join {join_channel.mention} to create their own temporary voice channel."
            ),
            color=0x00FF00
        )
        await msg.edit(content=None, embed=embed2)

    @commands.command(name='tvreset', aliases=['j2creset'])
    @commands.has_permissions(administrator=True)
    async def reset_tempvoice(self, ctx):
        if ctx.guild.id not in self.setup_data:
            await ctx.send("❌ TempVoice is not set up in this server!")
            return

        category = discord.utils.get(ctx.guild.categories, name=CATEGORY_NAME)
        if category:
            for ch in category.channels:
                try:
                    await ch.delete()
                except Exception:
                    pass
            try:
                await category.delete()
            except Exception:
                pass

        vc_ids = [vid for vid, d in self.private_channels.items() if d.get("guild_id") == ctx.guild.id]
        for vid in vc_ids:
            self.private_channels.pop(vid, None)

        self.setup_data.pop(ctx.guild.id, None)
        await self.delete_guild_setup(ctx.guild.id)

        await ctx.send("✅ TempVoice system has been completely reset!")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id not in self.setup_data:
            return

        guild_data = self.setup_data[member.guild.id]

        # User joins the "JOIN TO CREATE" channel
        if after.channel and after.channel.id == guild_data["join_channel_id"]:
            category = discord.utils.get(member.guild.categories, name=CATEGORY_NAME)
            if not category:
                return

            vc = await member.guild.create_voice_channel(
                f"{member.display_name}'s VC",
                category=category,
                user_limit=0
            )
            await member.move_to(vc)

            data = {
                "owner": member.id,
                "limit": 0,
                "region": "",
                "is_locked": False,
                "has_waiting_room": False,
                "chat_channel_id": 0,
                "guild_id": member.guild.id
            }
            await self.save_private_channel(vc.id, member.guild.id, data)

        # User leaves a temp VC
        if before.channel and before.channel.id in self.private_channels:
            vc_data = self.private_channels.get(before.channel.id, {})

            if (before.channel.id in self.blocked_users and
                    member.id in self.blocked_users[before.channel.id]):
                try:
                    await member.move_to(None)
                except Exception:
                    pass
                return

            if len(before.channel.members) == 0:
                chat_ch_id = vc_data.get("chat_channel_id", 0)
                if chat_ch_id:
                    chat_ch = member.guild.get_channel(chat_ch_id)
                    if chat_ch:
                        try:
                            await chat_ch.delete()
                        except Exception:
                            pass

                try:
                    await before.channel.delete()
                except Exception:
                    pass

                self.private_channels.pop(before.channel.id, None)
                await self.delete_private_channel(before.channel.id)

    async def get_owned_vc(self, interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice:
            return None
        vc = member.voice.channel
        if not vc:
            return None
        data = self.private_channels.get(vc.id)
        if not data:
            return None
        if data["owner"] == interaction.user.id or interaction.user.id in self.trusted_users.get(vc.id, []):
            return vc
        return None


class TempVoiceView(ui.View):
    def __init__(self, cog: JoinToCreate):
        super().__init__(timeout=None)
        self.cog = cog

    async def _owned_vc(self, interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            await interaction.response.send_message(
                "❌ You need to be in **your own** temp voice channel to use this!", ephemeral=True
            )
        return vc

    # ─── ROW 0 ────────────────────────────────────────────────────────────────

    @ui.button(label="NAME", style=discord.ButtonStyle.secondary, row=0, custom_id="tv:name", emoji="<:cd:1448949415200034907>")
    async def btn_name(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(RenameModal(vc))

    @ui.button(label="LIMIT", style=discord.ButtonStyle.secondary, row=0, custom_id="tv:limit", emoji="👥")
    async def btn_limit(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(LimitModal(vc, self.cog))

    @ui.button(label="PRIVACY", style=discord.ButtonStyle.secondary, row=0, custom_id="tv:privacy", emoji="🛡")
    async def btn_privacy(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        data = self.cog.private_channels[vc.id]
        is_locked = not data["is_locked"]
        await vc.set_permissions(interaction.guild.default_role, connect=not is_locked)
        data["is_locked"] = is_locked
        await self.cog.save_private_channel(vc.id, interaction.guild.id, data)
        await interaction.response.send_message(
            f"🔒 VC is now **{'locked' if is_locked else 'unlocked'}**!", ephemeral=True
        )

    @ui.button(label="WAITING ROOM", style=discord.ButtonStyle.secondary, row=0, custom_id="tv:waiting", emoji="⏳")
    async def btn_waiting(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        data = self.cog.private_channels[vc.id]
        has_wait = not data["has_waiting_room"]
        data["has_waiting_room"] = has_wait
        await self.cog.save_private_channel(vc.id, interaction.guild.id, data)
        await interaction.response.send_message(
            f"⏳ Waiting room **{'enabled' if has_wait else 'disabled'}**!", ephemeral=True
        )

    @ui.button(label="CHAT", style=discord.ButtonStyle.secondary, row=0, custom_id="tv:chat", emoji="💬")
    async def btn_chat(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        data = self.cog.private_channels[vc.id]
        chat_id = data.get("chat_channel_id", 0)

        if chat_id:
            existing = interaction.guild.get_channel(chat_id)
            if existing:
                await interaction.response.send_message(
                    f"💬 Chat channel already exists: {existing.mention}", ephemeral=True
                )
                return
        category = vc.category
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        for m in vc.members:
            overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        chat_ch = await interaction.guild.create_text_channel(
            f"💬-{vc.name}", category=category, overwrites=overwrites
        )
        data["chat_channel_id"] = chat_ch.id
        await self.cog.save_private_channel(vc.id, interaction.guild.id, data)
        await interaction.response.send_message(
            f"💬 Chat channel created: {chat_ch.mention}", ephemeral=True
        )

    # ─── ROW 1 ────────────────────────────────────────────────────────────────

    @ui.button(label="TRUST", style=discord.ButtonStyle.success, row=1, custom_id="tv:trust", emoji="👤")
    async def btn_trust(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        options = [
            SelectOption(label=m.display_name, value=str(m.id))
            for m in interaction.guild.members
            if not m.bot and m.id != interaction.user.id
            and m.id not in self.cog.trusted_users.get(vc.id, [])
        ][:25]
        if not options:
            await interaction.response.send_message("No members available to trust!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to trust", options, self._do_trust))
        await interaction.response.send_message("Select members to trust:", view=view, ephemeral=True)

    async def _do_trust(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        names = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m:
                await self.cog.trust_user(vc.id, m.id)
                await vc.set_permissions(m, connect=True, speak=True)
                names.append(m.display_name)
        await interaction.response.send_message(f"✅ Trusted: {', '.join(names)}", ephemeral=True)

    @ui.button(label="UNTRUST", style=discord.ButtonStyle.success, row=1, custom_id="tv:untrust", emoji="🚫")
    async def btn_untrust(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        trusted = self.cog.trusted_users.get(vc.id, [])
        options = [
            SelectOption(label=interaction.guild.get_member(uid).display_name, value=str(uid))
            for uid in trusted
            if interaction.guild.get_member(uid)
        ][:25]
        if not options:
            await interaction.response.send_message("No trusted members!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to untrust", options, self._do_untrust))
        await interaction.response.send_message("Select members to untrust:", view=view, ephemeral=True)

    async def _do_untrust(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        names = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m:
                await self.cog.untrust_user(vc.id, m.id)
                await vc.set_permissions(m, overwrite=None)
                names.append(m.display_name)
        await interaction.response.send_message(f"✅ Untrusted: {', '.join(names)}", ephemeral=True)

    @ui.button(label="INVITE", style=discord.ButtonStyle.success, row=1, custom_id="tv:invite", emoji="📞")
    async def btn_invite(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        options = [
            SelectOption(label=m.display_name, value=str(m.id))
            for m in interaction.guild.members
            if not m.bot and m not in vc.members
        ][:25]
        if not options:
            await interaction.response.send_message("No members to invite!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to invite", options, self._do_invite))
        await interaction.response.send_message("Select members to invite:", view=view, ephemeral=True)

    async def _do_invite(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        sent = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m:
                try:
                    await m.send(
                        f"📞 **{interaction.user.display_name}** has invited you to join **{vc.name}** in **{interaction.guild.name}**!"
                    )
                    sent.append(m.display_name)
                except Exception:
                    pass
        await interaction.response.send_message(
            f"✅ Invites sent to: {', '.join(sent)}" if sent else "❌ Could not send invites (DMs disabled).",
            ephemeral=True
        )

    @ui.button(label="KICK", style=discord.ButtonStyle.success, row=1, custom_id="tv:kick", emoji="👢")
    async def btn_kick(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        options = [
            SelectOption(label=m.display_name, value=str(m.id))
            for m in vc.members
            if m.id != interaction.user.id
        ]
        if not options:
            await interaction.response.send_message("No members to kick!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to kick", options, self._do_kick))
        await interaction.response.send_message("Select members to kick:", view=view, ephemeral=True)

    async def _do_kick(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        names = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m and m in vc.members:
                try:
                    await m.move_to(None)
                    names.append(m.display_name)
                except Exception:
                    pass
        await interaction.response.send_message(f"👢 Kicked: {', '.join(names)}", ephemeral=True)

    @ui.button(label="REGION", style=discord.ButtonStyle.success, row=1, custom_id="tv:region", emoji="🌍")
    async def btn_region(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        regions = [
            SelectOption(label="Automatic", value="auto"),
            SelectOption(label="🇺🇸 US West", value="us-west"),
            SelectOption(label="🇺🇸 US East", value="us-east"),
            SelectOption(label="🇺🇸 US Central", value="us-central"),
            SelectOption(label="🇺🇸 US South", value="us-south"),
            SelectOption(label="🇪🇺 Europe", value="europe"),
            SelectOption(label="🇸🇬 Singapore", value="singapore"),
            SelectOption(label="🇯🇵 Japan", value="japan"),
            SelectOption(label="🇧🇷 Brazil", value="brazil"),
            SelectOption(label="🇦🇺 Australia", value="sydney"),
            SelectOption(label="🇿🇦 South Africa", value="southafrica"),
            SelectOption(label="🇮🇳 India", value="india"),
        ]
        view = ui.View()
        view.add_item(RegionSelect(regions, vc, self.cog))
        await interaction.response.send_message("🌍 Select a region:", view=view, ephemeral=True)

    # ─── ROW 2 ────────────────────────────────────────────────────────────────

    @ui.button(label="BLOCK", style=discord.ButtonStyle.danger, row=2, custom_id="tv:block", emoji="🚷")
    async def btn_block(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        options = [
            SelectOption(label=m.display_name, value=str(m.id))
            for m in interaction.guild.members
            if not m.bot and m.id != interaction.user.id
            and m.id not in self.cog.blocked_users.get(vc.id, [])
        ][:25]
        if not options:
            await interaction.response.send_message("No members to block!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to block", options, self._do_block))
        await interaction.response.send_message("Select members to block:", view=view, ephemeral=True)

    async def _do_block(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        names = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m:
                await self.cog.block_user(vc.id, m.id)
                await vc.set_permissions(m, connect=False)
                if m in vc.members:
                    try:
                        await m.move_to(None)
                    except Exception:
                        pass
                names.append(m.display_name)
        await interaction.response.send_message(f"🚷 Blocked: {', '.join(names)}", ephemeral=True)

    @ui.button(label="UNBLOCK", style=discord.ButtonStyle.danger, row=2, custom_id="tv:unblock", emoji="🔓")
    async def btn_unblock(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        blocked = self.cog.blocked_users.get(vc.id, [])
        options = [
            SelectOption(label=interaction.guild.get_member(uid).display_name, value=str(uid))
            for uid in blocked
            if interaction.guild.get_member(uid)
        ][:25]
        if not options:
            await interaction.response.send_message("No blocked members!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select members to unblock", options, self._do_unblock))
        await interaction.response.send_message("Select members to unblock:", view=view, ephemeral=True)

    async def _do_unblock(self, interaction: discord.Interaction, values: List[str]):
        vc = await self.cog.get_owned_vc(interaction)
        if not vc:
            return
        names = []
        for uid in values:
            m = interaction.guild.get_member(int(uid))
            if m:
                await self.cog.unblock_user(vc.id, m.id)
                await vc.set_permissions(m, overwrite=None)
                names.append(m.display_name)
        await interaction.response.send_message(f"🔓 Unblocked: {', '.join(names)}", ephemeral=True)

    @ui.button(label="CLAIM", style=discord.ButtonStyle.danger, row=2, custom_id="tv:claim", emoji="👑")
    async def btn_claim(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice:
            await interaction.response.send_message("❌ You must be in a voice channel to claim it!", ephemeral=True)
            return
        vc = member.voice.channel
        data = self.cog.private_channels.get(vc.id if vc else 0)
        if not data:
            await interaction.response.send_message("❌ This is not a temp voice channel!", ephemeral=True)
            return
        owner = interaction.guild.get_member(data["owner"])
        if owner and owner in vc.members:
            await interaction.response.send_message("❌ The owner is still in the VC!", ephemeral=True)
            return
        data["owner"] = interaction.user.id
        await self.cog.save_private_channel(vc.id, interaction.guild.id, data)
        await interaction.response.send_message(f"👑 You've claimed **{vc.name}**!", ephemeral=True)

    @ui.button(label="TRANSFER", style=discord.ButtonStyle.danger, row=2, custom_id="tv:transfer", emoji="🔄")
    async def btn_transfer(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        data = self.cog.private_channels.get(vc.id, {})
        if data.get("owner") != interaction.user.id:
            await interaction.response.send_message("❌ Only the **owner** can transfer!", ephemeral=True)
            return
        options = [
            SelectOption(label=m.display_name, value=str(m.id))
            for m in vc.members
            if m.id != interaction.user.id
        ]
        if not options:
            await interaction.response.send_message("No members to transfer to!", ephemeral=True)
            return
        view = ui.View()
        view.add_item(MemberSelect("Select new owner", options, self._do_transfer, max_v=1))
        await interaction.response.send_message("Select new owner:", view=view, ephemeral=True)

    async def _do_transfer(self, interaction: discord.Interaction, values: List[str]):
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice:
            return
        vc = member.voice.channel
        if not vc or vc.id not in self.cog.private_channels:
            return
        new_owner = interaction.guild.get_member(int(values[0]))
        if not new_owner:
            return
        self.cog.private_channels[vc.id]["owner"] = new_owner.id
        await self.cog.save_private_channel(vc.id, interaction.guild.id, self.cog.private_channels[vc.id])
        await interaction.response.send_message(
            f"🔄 Transferred ownership to **{new_owner.display_name}**!", ephemeral=True
        )

    @ui.button(label="DELETE", style=discord.ButtonStyle.danger, row=2, custom_id="tv:delete", emoji="🗑")
    async def btn_delete(self, interaction: discord.Interaction, button: ui.Button):
        vc = await self._owned_vc(interaction)
        if not vc:
            return
        data = self.cog.private_channels.get(vc.id, {})
        if data.get("owner") != interaction.user.id:
            await interaction.response.send_message("❌ Only the **owner** can delete the VC!", ephemeral=True)
            return
        chat_id = data.get("chat_channel_id", 0)
        if chat_id:
            ch = interaction.guild.get_channel(chat_id)
            if ch:
                try:
                    await ch.delete()
                except Exception:
                    pass
        for m in vc.members:
            try:
                await m.move_to(None)
            except Exception:
                pass
        await vc.delete()
        self.cog.private_channels.pop(vc.id, None)
        await self.cog.delete_private_channel(vc.id)
        await interaction.response.send_message("🗑 Your temp VC has been deleted!", ephemeral=True)


# ─── Helper UI Components ──────────────────────────────────────────────────────

class MemberSelect(ui.Select):
    def __init__(self, placeholder: str, options: List[SelectOption], cb, max_v: int = 25):
        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=min(max_v, len(options))
        )
        self._cb = cb

    async def callback(self, interaction: discord.Interaction):
        await self._cb(interaction, self.values)


class RegionSelect(ui.Select):
    def __init__(self, options: List[SelectOption], vc: discord.VoiceChannel, cog: JoinToCreate):
        super().__init__(placeholder="Select a region", options=options)
        self.vc = vc
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        region = self.values[0]
        try:
            await self.vc.edit(rtc_region=None if region == "auto" else region)
            if self.vc.id in self.cog.private_channels:
                self.cog.private_channels[self.vc.id]["region"] = region
                await self.cog.save_private_channel(
                    self.vc.id, interaction.guild.id, self.cog.private_channels[self.vc.id]
                )
            await interaction.response.send_message(f"🌍 Region set to **{region}**!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {e}", ephemeral=True)


class RenameModal(ui.Modal, title="Rename Your Voice Channel"):
    def __init__(self, vc: discord.VoiceChannel):
        super().__init__()
        self.vc = vc
        self.name = ui.TextInput(
            label="New channel name",
            placeholder="Enter a new name...",
            default=vc.name,
            max_length=100
        )
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.vc.edit(name=self.name.value)
            await interaction.response.send_message(
                f"✅ Channel renamed to **{self.name.value}**!", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {e}", ephemeral=True)


class LimitModal(ui.Modal, title="Set Member Limit"):
    def __init__(self, vc: discord.VoiceChannel, cog: JoinToCreate):
        super().__init__()
        self.vc = vc
        self.cog = cog
        self.limit = ui.TextInput(
            label="User limit (0 = unlimited)",
            placeholder="Enter 0-99",
            default=str(vc.user_limit) if vc.user_limit else "0",
            max_length=2
        )
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit.value)
            if val < 0 or val > 99:
                raise ValueError
            await self.vc.edit(user_limit=val if val != 0 else None)
            if self.vc.id in self.cog.private_channels:
                self.cog.private_channels[self.vc.id]["limit"] = val
                await self.cog.save_private_channel(
                    self.vc.id, interaction.guild.id, self.cog.private_channels[self.vc.id]
                )
            await interaction.response.send_message(
                f"✅ Limit set to **{'unlimited' if val == 0 else val}**!", ephemeral=True
            )
        except Exception:
            await interaction.response.send_message("❌ Enter a valid number between 0 and 99.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(JoinToCreate(bot))
