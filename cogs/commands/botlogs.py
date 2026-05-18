from __future__ import annotations
import discord
import aiosqlite
import asyncio
import os
import datetime
import platform
import psutil
from discord.ext import commands
from core import Cog, zyrox

DB_PATH        = 'db/botlogs.db'
LOG_SERVER_ID  = 1504060120492146708   # Emoji Server 1 — logs channel yahan banta hai
OWNER_IDS      = [1258831252748894436, 870179991462236170, 1432771000629596225,
                  1382744437049790495, 1255716509443948648]

CUSTOM_COMMANDS = [
    ("👑 Owner Only", [
        (">owners",          "Sare owners ki list"),
        (">staff_add @user", "Kisi ko staff add karo"),
        (">staff_remove @u", "Staff remove karo"),
        (">staff_list",      "Staff list dekho"),
        (">getadmin",        "Current server mein admin role lo"),
        (">getinvite [id]",  "Kisi server ka invite lo"),
        (">guildinfo [id]",  "Kisi server ki info dekho"),
        (">leaveguild [id]", "Bot ko kisi server se hatao"),
        (">reload",          "Bot cogs reload karo"),
        (">sync",            "Database sync karo"),
        (">massdm <msg>",    "Sare users ko DM karo"),
        (">ownerban [id]",   "Kisi bhi server se ban"),
        (">ownerunban [id]", "Global unban"),
        (">guildban [sv]",   "Kisi server se ban karo"),
        (">mutuals @user",   "Common servers dekho"),
    ]),
    ("🎨 Emoji Management", [
        (">synchemoji",      "Sare emojis sync karo"),
        (">listemoji",       "Saved emojis list"),
        (">findemoji <nam>", "Emoji dhundho by name"),
    ]),
    ("🎭 Auto Nick", [
        (">autonick set",    "Auto nickname prefix set"),
        (">autonick disable","Auto nick band karo"),
        (">autonick show",   "Current setting dekho"),
        (">freezenick @u",   "Nick lock karo (change nahi hoga)"),
        (">unfreezenick @u", "Nick unlock karo"),
    ]),
    ("🔐 Bot Logs", [
        (">setlogs #ch",     "Log channel set karo"),
        (">removelogs",      "Logs band karo"),
        (">logstatus",       "Current log channel dekho"),
        (">health",          "Bot system health check"),
        (">ownerhelp",       "Yeh custom commands table"),
        (">pcsetup",         "PC setup PowerShell command"),
    ]),
    ("📬 DM Relay", [
        (">dmrelaystatus",   "DM relay server status"),
    ]),
    ("🎵 24/7 Music", [
        (">247 enable",      "Voice channel mein 24/7 music"),
        (">247 disable",     "Music band karo"),
        (">247 stream",      "Stream change karo (lofi/chill/beats)"),
    ]),
]


async def _db():
    os.makedirs('db', exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
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

async def _get_location() -> str:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get('http://ip-api.com/json/?fields=country,city,isp', timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                city    = data.get('city', '?')
                country = data.get('country', '?')
                isp     = data.get('isp', '?')
                return f"{city}, {country} ({isp})"
    except Exception:
        return "Unknown"

async def send_bot_log(bot: discord.Client, title: str, description: str,
                       color: discord.Color = discord.Color.blurple(),
                       fields: list[tuple] = None):
    channel_id = await get_log_channel_id()
    if not channel_id:
        return
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        embed   = discord.Embed(title=title, description=description, color=color,
                                timestamp=datetime.datetime.utcnow())
        source  = os.environ.get('BOT_SOURCE', 'Replit ☁️')
        embed.set_footer(text=f"Source: {source}")
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[BotLogs] {e}")


class BotLogs(Cog):
    def __init__(self, bot: zyrox):
        self.bot = bot

    def _is_owner(self, uid: int) -> bool:
        return uid in OWNER_IDS

    # ── Auto-create logs channel in Emoji Server 1 ────────────────────────────

    async def _ensure_log_channel(self):
        """Emoji Server 1 mein #bot-logs channel auto-create karo agar nahi hai"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(8)
        guild = self.bot.get_guild(LOG_SERVER_ID)
        if not guild:
            return

        existing_id = await get_log_channel_id()
        if existing_id:
            ch = guild.get_channel(existing_id)
            if ch:
                return   # already set

        # Find existing channel named bot-logs
        ch = discord.utils.get(guild.text_channels, name='bot-logs')
        if not ch:
            try:
                # Try to find/create a category
                category = discord.utils.get(guild.categories, name='📋 Bot Logs') or \
                           discord.utils.get(guild.categories, name='Logs') or \
                           discord.utils.get(guild.categories, name='BOT')
                ch = await guild.create_text_channel('bot-logs', category=category,
                    topic="DARK INFINITE bot ke advanced logs — owner only")
                print(f"[BotLogs] Created #bot-logs in {guild.name}")
            except Exception as e:
                print(f"[BotLogs] Could not create channel: {e}")
                return

        # Save to DB
        async with await _db() as conn:
            await conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('log_channel', ?)",
                               (str(ch.id),))
            await conn.commit()
        print(f"[BotLogs] Log channel set → #{ch.name} in {guild.name}")

    # ── Startup log with full system info ─────────────────────────────────────

    async def _send_startup_log(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(12)
        try:
            source   = os.environ.get('BOT_SOURCE', 'Replit ☁️')
            location = await _get_location()
            cpu      = psutil.cpu_percent(interval=1)
            ram      = psutil.virtual_memory()
            os_name  = f"{platform.system()} {platform.release()}"
            latency  = round(self.bot.latency * 1000)

            await send_bot_log(
                self.bot,
                "🟢 DARK INFINITE — Online!",
                f"Bot successfully start ho gaya hai.",
                color=discord.Color.green(),
                fields=[
                    ("🖥️ Running On",   f"`{source}`",                                True),
                    ("📍 Location",     f"`{location}`",                              True),
                    ("💻 OS",          f"`{os_name}`",                               True),
                    ("⚡ Ping",         f"`{latency}ms`",                             True),
                    ("🧠 RAM",          f"`{ram.percent}% used ({ram.used//1024//1024}MB)`", True),
                    ("🔥 CPU",          f"`{cpu}%`",                                  True),
                    ("🌐 Guilds",       str(len(self.bot.guilds)),                    True),
                    ("⚡ Commands",     str(len(list(self.bot.commands))),            True),
                    ("🕐 Time (UTC)",   f"`{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}`", False),
                ]
            )
        except Exception as e:
            print(f"[BotLogs] Startup log error: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.loop.create_task(self._ensure_log_channel())
        self.bot.loop.create_task(self._send_startup_log())

    # ── >health command ───────────────────────────────────────────────────────

    @commands.command(name="health", aliases=["botinfo", "status", "sysinfo"])
    async def health(self, ctx: commands.Context):
        """Bot system health check"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Owner only command hai yeh.")

        source   = os.environ.get('BOT_SOURCE', 'Replit ☁️')
        location = await _get_location()
        cpu      = psutil.cpu_percent(interval=1)
        ram      = psutil.virtual_memory()
        disk     = psutil.disk_usage('/')
        latency  = round(self.bot.latency * 1000)
        os_name  = f"{platform.system()} {platform.release()}"

        color = discord.Color.green() if latency < 150 else \
                discord.Color.orange() if latency < 400 else discord.Color.red()

        embed = discord.Embed(
            title="🏥 Bot Health Report",
            color=color,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="🖥️ Running On",  value=f"`{source}`",                                    inline=True)
        embed.add_field(name="📍 Location",    value=f"`{location}`",                                   inline=True)
        embed.add_field(name="💻 OS",          value=f"`{os_name}`",                                    inline=True)
        embed.add_field(name="⚡ Ping",         value=f"`{latency}ms`",                                  inline=True)
        embed.add_field(name="🧠 RAM",          value=f"`{ram.percent}%` ({ram.used//1024//1024}MB/{ram.total//1024//1024}MB)", inline=True)
        embed.add_field(name="🔥 CPU",          value=f"`{cpu}%`",                                       inline=True)
        embed.add_field(name="💾 Disk",         value=f"`{disk.percent}%` used",                         inline=True)
        embed.add_field(name="🌐 Guilds",       value=str(len(self.bot.guilds)),                         inline=True)
        embed.add_field(name="⚡ Commands",     value=str(len(list(self.bot.commands))),                 inline=True)
        embed.add_field(name="🐍 Python",       value=f"`{platform.python_version()}`",                  inline=True)
        embed.set_footer(text="DARK INFINITE System Check")
        await ctx.reply(embed=embed)

    # ── >ownerhelp — custom commands table ───────────────────────────────────

    @commands.command(name="ownerhelp", aliases=["customcmds", "owncmds", "mycmds"])
    async def owner_help(self, ctx: commands.Context):
        """Owner ke saare custom commands ki list"""
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Owner only command hai yeh.")

        embeds = []
        for category, cmd_list in CUSTOM_COMMANDS:
            embed = discord.Embed(title=f"📋 {category}", color=0xe03030)
            lines = "\n".join(f"`{cmd:<22}` {desc}" for cmd, desc in cmd_list)
            embed.description = lines
            embeds.append(embed)

        # Send all embeds
        for embed in embeds:
            await ctx.send(embed=embed)

    # ── >setlogs / >removelogs / >logstatus ──────────────────────────────────

    @commands.command(name="setlogs", aliases=["setlogchannel", "botlogs"])
    async def setlogs(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain.")
        channel = channel or ctx.channel
        async with await _db() as conn:
            await conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('log_channel', ?)",
                               (str(channel.id),))
            await conn.commit()
        embed = discord.Embed(title="✅ Log Channel Set!", color=discord.Color.green(),
                              description=f"Logs ab {channel.mention} mein aayenge.")
        embed.add_field(name="Kya log hoga", value=(
            "🟢 Bot Online (source + location)\n🔴 Bot Offline\n"
            "🔄 Auto-update\n🖥️ PC switch\n❌ Errors"), inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name="removelogs", aliases=["disablelogs"])
    async def removelogs(self, ctx: commands.Context):
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain.")
        async with await _db() as conn:
            await conn.execute("DELETE FROM config WHERE key='log_channel'")
            await conn.commit()
        await ctx.reply(embed=discord.Embed(title="🗑️ Logs Disabled", color=discord.Color.red()))

    @commands.command(name="logstatus", aliases=["checklog"])
    async def logstatus(self, ctx: commands.Context):
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain.")
        ch_id  = await get_log_channel_id()
        source = os.environ.get('BOT_SOURCE', 'Replit ☁️')
        if not ch_id:
            return await ctx.reply(embed=discord.Embed(
                title="❌ No Log Channel",
                description="Koi log channel set nahi.\n`>setlogs #channel` se set karo.",
                color=discord.Color.red()))
        ch   = self.bot.get_channel(ch_id)
        name = ch.mention if ch else f"<#{ch_id}>"
        embed = discord.Embed(title="📋 Log Status", color=discord.Color.blurple())
        embed.add_field(name="📌 Log Channel",     value=name,          inline=True)
        embed.add_field(name="🖥️ Running On",      value=f"`{source}`", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="pcsetup", aliases=["setupcommand", "getsetup"])
    async def pcsetup(self, ctx: commands.Context):
        if not self._is_owner(ctx.author.id):
            return await ctx.reply("❌ Sirf owners use kar sakte hain.")
        try:
            with open('replit_url.txt') as f:
                bot_url = f.read().strip()
        except Exception:
            bot_url = "YOUR_BOT_URL"
        embed = discord.Embed(title="🖥️ PC Setup Command", color=discord.Color.blue(),
                              description=(
                                  "**PowerShell (Admin) mein paste karo:**\n"
                                  f"```powershell\nirm {bot_url}/setup.ps1 | iex\n```\n"
                                  "✅ Python auto-install · ✅ Auto-update · ✅ 24/7 failover"))
        await ctx.reply(embed=embed)


async def setup(bot: zyrox):
    await bot.add_cog(BotLogs(bot))
