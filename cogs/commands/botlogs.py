from __future__ import annotations
import discord
import aiosqlite
import os
import datetime
from discord.ext import commands
from core import Cog, zyrox, Context

DB_PATH = 'db/botlogs.db'
OWNER_IDS = [1258831252748894436, 870179991462236170, 1432771000629596225,
             1382744437049790495, 1255716509443948648]

async def _db():
    os.makedirs('db', exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)"
    )
    await conn.commit()
    return conn

async def get_log_channel_id() -> int | None:
    try:
        async with await _db() as conn:
            async with conn.execute("SELECT value FROM config WHERE key='log_channel'") as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else None
    except Exception:
        return None

async def send_bot_log(bot: discord.Client, title: str, description: str,
                       color: discord.Color = discord.Color.blurple(),
                       fields: list[tuple] = None):
    channel_id = await get_log_channel_id()
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    try:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.datetime.utcnow()
        )
        source = os.environ.get('BOT_SOURCE', 'Replit ☁️')
        embed.set_footer(text=f"Source: {source}")
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[BotLogs] Could not send log: {e}")


class BotLogs(Cog):
    def __init__(self, bot: zyrox):
        self.bot = bot

    def _is_owner(self, user_id: int) -> bool:
        return user_id in OWNER_IDS

    @commands.command(name="setlogs", aliases=["setlogchannel", "botlogs"])
    async def setlogs(self, ctx: Context, channel: discord.TextChannel = None):
        """Set the channel where bot activity logs will be sent (Owner only)"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain yeh command.")

        if channel is None:
            channel = ctx.channel

        async with await _db() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('log_channel', ?)",
                (str(channel.id),)
            )
            await conn.commit()

        embed = discord.Embed(
            title="✅ Bot Logs Channel Set!",
            description=f"Ab sare bot activity logs {channel.mention} mein aayenge.",
            color=discord.Color.green()
        )
        embed.add_field(name="📋 Kya log hoga?", value=(
            "🟢 Bot Online (Replit/PC se)\n"
            "🔴 Bot Offline\n"
            "🔄 Auto-update (naya version)\n"
            "🖥️ PC switch (kaun sa PC chal raha hai)\n"
            "❌ Errors & crashes"
        ), inline=False)
        embed.set_footer(text=f"Set by {ctx.author}")
        await ctx.reply(embed=embed)

        await send_bot_log(
            self.bot,
            "📋 Log Channel Configured",
            f"Bot logs is channel mein set ho gaye: {channel.mention}",
            color=discord.Color.green()
        )

    @commands.command(name="removelogs", aliases=["disablelogs"])
    async def removelogs(self, ctx: Context):
        """Remove the bot log channel (Owner only)"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain yeh command.")

        async with await _db() as conn:
            await conn.execute("DELETE FROM config WHERE key='log_channel'")
            await conn.commit()

        await ctx.reply(embed=discord.Embed(
            title="🗑️ Bot Logs Disabled",
            description="Ab koi bhi logs kisi channel mein nahi aayenge.",
            color=discord.Color.red()
        ))

    @commands.command(name="logstatus", aliases=["checklog"])
    async def logstatus(self, ctx: Context):
        """Check current log channel (Owner only)"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain yeh command.")

        channel_id = await get_log_channel_id()
        if not channel_id:
            return await ctx.reply(embed=discord.Embed(
                title="❌ No Log Channel",
                description="Koi log channel set nahi hai.\nUse `$setlogs #channel` to set one.",
                color=discord.Color.red()
            ))

        channel = self.bot.get_channel(channel_id)
        name = channel.mention if channel else f"<#{channel_id}>"
        source = os.environ.get('BOT_SOURCE', 'Replit ☁️')

        embed = discord.Embed(
            title="📋 Bot Logs Status",
            color=discord.Color.blurple()
        )
        embed.add_field(name="📌 Log Channel", value=name, inline=True)
        embed.add_field(name="🖥️ Currently Running On", value=f"`{source}`", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="pcsetup", aliases=["setupcommand", "getsetup"])
    async def pcsetup(self, ctx: Context):
        """Get the final PowerShell setup command for PC (Owner only)"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain yeh command.")

        bot_url = os.environ.get('REPLIT_URL', 'YOUR_REPLIT_URL')
        if bot_url == 'YOUR_REPLIT_URL':
            try:
                with open('replit_url.txt') as f:
                    bot_url = f.read().strip()
            except Exception:
                pass

        cmd = (
            f"irm {bot_url}/setup.ps1 | iex"
        )

        embed = discord.Embed(
            title="🖥️ PC Setup Command",
            description=(
                "**PC pe PowerShell (Admin) mein yeh run karo:**\n"
                f"```powershell\n{cmd}\n```\n"
                "Yeh ek command sab kuch karega:\n"
                "✅ Python install\n"
                "✅ Bot download\n"
                "✅ Auto-start on boot\n"
                "✅ Auto-update jab Replit pe change ho\n"
                "✅ PC dashboard mein register\n"
                "✅ 24/7 failover (Replit offline hone pe)"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Run as Administrator for best results")
        await ctx.reply(embed=embed)


async def setup(bot: zyrox):
    await bot.add_cog(BotLogs(bot))
