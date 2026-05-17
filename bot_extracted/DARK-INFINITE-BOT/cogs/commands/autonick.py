from __future__ import annotations
import discord
import aiosqlite
from discord.ext import commands
from utils.Tools import *
from core import Cog, Context

DB_PATH = 'db/autonick.db'

class AutoNick(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.create_table())

    async def create_table(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS autonick (
                    guild_id INTEGER PRIMARY KEY,
                    prefix TEXT NOT NULL
                )
            """)
            await db.commit()

    async def get_prefix(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT prefix FROM autonick WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        prefix = await self.get_prefix(member.guild.id)
        if not prefix:
            return
        new_nick = f"{prefix} {member.display_name}"
        if len(new_nick) > 32:
            new_nick = new_nick[:32]
        try:
            await member.edit(nick=new_nick)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.group(name="autonick", aliases=["autonickname", "anick"], invoke_without_command=True, case_insensitive=True)
    @commands.has_permissions(manage_nicknames=True)
    @blacklist_check()
    @ignore_check()
    async def autonick(self, ctx: Context):
        prefix = await self.get_prefix(ctx.guild.id)
        embed = discord.Embed(color=0xFF0000)
        embed.set_author(name="Auto Nick", icon_url=self.bot.user.display_avatar.url)
        if prefix:
            embed.description = (
                f"<:ztick:1504088022642200606> Auto Nick is **enabled** on this server.\n"
                f"**Current Prefix:** `{prefix}`\n\n"
                f"New members will get: `{prefix} <username>`\n\n"
                f"**Commands:**\n"
                f"`autonick set <prefix>` — prefix set karo\n"
                f"`autonick disable` — band karo\n"
                f"`autonick show` — current prefix dekho"
            )
        else:
            embed.description = (
                "<:zwarning:1504091612047999058> Auto Nick is **disabled** on this server.\n\n"
                "**Commands:**\n"
                "`autonick set <prefix>` — prefix set karo\n"
                "`autonick disable` — band karo\n"
                "`autonick show` — current prefix dekho"
            )
        await ctx.reply(embed=embed, mention_author=False)

    @autonick.command(name="set", aliases=["enable", "on", "add"])
    @commands.has_permissions(manage_nicknames=True)
    @blacklist_check()
    @ignore_check()
    async def autonick_set(self, ctx: Context, *, prefix: str):
        if len(prefix) > 20:
            embed = discord.Embed(
                description="<:zwarning:1504091612047999058> Prefix 20 characters se zyada nahi ho sakta.",
                color=0xFF0000
            )
            return await ctx.reply(embed=embed, mention_author=False)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO autonick (guild_id, prefix) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET prefix = ?",
                (ctx.guild.id, prefix, prefix)
            )
            await db.commit()

        embed = discord.Embed(color=0xFF0000)
        embed.set_author(name="Auto Nick Enabled", icon_url=self.bot.user.display_avatar.url)
        embed.description = (
            f"<:ztick:1504088022642200606> Auto Nick set ho gaya!\n\n"
            f"**Prefix:** `{prefix}`\n"
            f"**Example:** `{prefix} Username`\n\n"
            f"Ab jab bhi koi naya member join karega, unka nick automatically `{prefix} <unka naam>` ho jayega."
        )
        await ctx.reply(embed=embed, mention_author=False)

    @autonick.command(name="disable", aliases=["remove", "off", "reset"])
    @commands.has_permissions(manage_nicknames=True)
    @blacklist_check()
    @ignore_check()
    async def autonick_disable(self, ctx: Context):
        prefix = await self.get_prefix(ctx.guild.id)
        if not prefix:
            embed = discord.Embed(
                description="<:zwarning:1504091612047999058> Auto Nick pehle se hi **OFF** hai is server mein.",
                color=0xFF0000
            )
            return await ctx.reply(embed=embed, mention_author=False)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM autonick WHERE guild_id = ?", (ctx.guild.id,))
            await db.commit()

        embed = discord.Embed(
            description="<:ztick:1504088022642200606> Auto Nick **band** kar diya gaya. Ab naye members ka nick automatically nahi lagega.",
            color=0xFF0000
        )
        await ctx.reply(embed=embed, mention_author=False)

    @autonick.command(name="show", aliases=["status", "check"])
    @commands.has_permissions(manage_nicknames=True)
    @blacklist_check()
    @ignore_check()
    async def autonick_show(self, ctx: Context):
        prefix = await self.get_prefix(ctx.guild.id)
        embed = discord.Embed(color=0xFF0000)
        embed.set_author(name="Auto Nick Status", icon_url=self.bot.user.display_avatar.url)
        if prefix:
            embed.description = (
                f"<:ztick:1504088022642200606> Auto Nick **ON** hai.\n"
                f"**Prefix:** `{prefix}`\n"
                f"**Format:** `{prefix} <member name>`"
            )
        else:
            embed.description = "<:zwarning:1504091612047999058> Auto Nick abhi **OFF** hai."
        await ctx.reply(embed=embed, mention_author=False)

async def setup(bot):
    await bot.add_cog(AutoNick(bot))
