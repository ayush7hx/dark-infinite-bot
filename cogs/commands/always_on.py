import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio

DB = "db/247music.db"

LOFI_STREAMS = {
    "lofi":   "https://streams.ilovemusic.de/iloveradio17.mp3",
    "chill":  "https://streams.ilovemusic.de/iloveradio2.mp3",
    "beats":  "https://streams.ilovemusic.de/iloveradio10.mp3",
}
DEFAULT_STREAM = LOFI_STREAMS["lofi"]

OWNER_ID = 1255716509443948648


class AlwaysOn(commands.Cog, name="AlwaysOn"):
    def __init__(self, bot):
        self.bot = bot
        self._joining: set = set()
        self.auto_rejoin_loop.start()

    def cog_unload(self):
        self.auto_rejoin_loop.cancel()

    # ── DB helpers ─────────────────────────────────────────────────────────────

    async def _ensure_db(self):
        async with aiosqlite.connect(DB) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS always_on (
                    guild_id   INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    stream_url TEXT    DEFAULT NULL,
                    enabled    INTEGER DEFAULT 1
                )
            """)
            await db.commit()

    async def _get(self, guild_id: int):
        await self._ensure_db()
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT channel_id, stream_url, enabled FROM always_on WHERE guild_id=?",
                (guild_id,))
            return await cur.fetchone()

    async def _set(self, guild_id: int, channel_id: int, stream_url: str = None):
        await self._ensure_db()
        async with aiosqlite.connect(DB) as db:
            await db.execute("""
                INSERT INTO always_on (guild_id, channel_id, stream_url, enabled)
                VALUES (?,?,?,1)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    stream_url=excluded.stream_url,
                    enabled=1
            """, (guild_id, channel_id, stream_url))
            await db.commit()

    async def _disable(self, guild_id: int):
        await self._ensure_db()
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE always_on SET enabled=0 WHERE guild_id=?", (guild_id,))
            await db.commit()

    async def _all_enabled(self):
        await self._ensure_db()
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT guild_id, channel_id, stream_url FROM always_on WHERE enabled=1")
            return await cur.fetchall()

    # ── Internal: join & stream ────────────────────────────────────────────────

    async def _join_and_stream(self, channel: discord.VoiceChannel, stream_url: str = None):
        guild = channel.guild
        if guild.id in self._joining:
            return
        self._joining.add(guild.id)
        try:
            url = stream_url or DEFAULT_STREAM
            vc: discord.VoiceClient = guild.voice_client

            if vc and vc.channel.id == channel.id and vc.is_connected():
                if not vc.is_playing():
                    src = discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
                    vc.play(src, after=lambda e: asyncio.run_coroutine_threadsafe(
                        self._on_track_end(guild.id, url), self.bot.loop))
                return

            if vc:
                await vc.disconnect(force=True)
                await asyncio.sleep(1)

            vc = await channel.connect(reconnect=True)
            await asyncio.sleep(0.5)
            src = discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
            vc.play(src, after=lambda e: asyncio.run_coroutine_threadsafe(
                self._on_track_end(guild.id, url), self.bot.loop))
            print(f"[247Music] Joined #{channel.name} in {guild.name} and started streaming.")
        except Exception as ex:
            print(f"[247Music] Error joining {guild.name}: {ex}")
        finally:
            self._joining.discard(guild.id)

    async def _on_track_end(self, guild_id: int, url: str):
        await asyncio.sleep(2)
        row = await self._get(guild_id)
        if row and row[2]:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(row[0])
                if channel:
                    await self._join_and_stream(channel, url)

    # ── Auto-rejoin loop (every 60s) ───────────────────────────────────────────

    @tasks.loop(seconds=60)
    async def auto_rejoin_loop(self):
        for row in await self._all_enabled():
            guild_id, channel_id, stream_url = row
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                continue
            vc = guild.voice_client
            if not vc or not vc.is_connected() or not vc.is_playing():
                await self._join_and_stream(channel, stream_url)

    @auto_rejoin_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)

    # ── on_ready: auto-join all enabled guilds ─────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(8)
        for row in await self._all_enabled():
            guild_id, channel_id, stream_url = row
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.VoiceChannel):
                await self._join_and_stream(channel, stream_url)

    # ── on_voice_state_update: rejoin if bot is kicked ────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            await asyncio.sleep(3)
            row = await self._get(member.guild.id)
            if row and row[2]:
                channel = member.guild.get_channel(row[0])
                if channel and isinstance(channel, discord.VoiceChannel):
                    await self._join_and_stream(channel, row[1])

    # ── Commands ───────────────────────────────────────────────────────────────

    @commands.group(name="247", aliases=["24x7", "nonstop", "247music"],
                    invoke_without_command=True)
    @commands.guild_only()
    async def always_on_group(self, ctx: commands.Context):
        row = await self._get(ctx.guild.id)
        if row and row[2]:
            ch = ctx.guild.get_channel(row[0])
            status = "🟢 **Enabled**" if row[2] else "🔴 **Disabled**"
            ch_name = ch.mention if ch else f"<#{row[0]}>"
            stream = row[1] or DEFAULT_STREAM
            e = discord.Embed(title="24/7 Music Status", color=0xFF0000)
            e.add_field(name="Status",  value=status,  inline=True)
            e.add_field(name="Channel", value=ch_name, inline=True)
            e.add_field(name="Stream",  value=f"`{stream}`", inline=False)
            e.set_footer(text="Use >247 enable / >247 disable")
            await ctx.send(embed=e)
        else:
            e = discord.Embed(
                description="**24/7 Music** is not enabled.\nUse `>247 enable` while in a voice channel.",
                color=0xFF0000)
            await ctx.send(embed=e)

    @always_on_group.command(name="enable", aliases=["start", "on"])
    @commands.guild_only()
    async def enable_247(self, ctx: commands.Context,
                         channel: discord.VoiceChannel = None,
                         stream_key: str = "lofi"):
        if not (ctx.author.guild_permissions.manage_guild or
                ctx.author.id == OWNER_ID or
                ctx.author.id == ctx.guild.owner_id):
            return await ctx.send(embed=discord.Embed(
                description="❌ You need **Manage Server** permission.", color=0xFF0000))

        if channel is None:
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
            else:
                return await ctx.send(embed=discord.Embed(
                    description="❌ Join a voice channel first or mention one: `>247 enable #channel`",
                    color=0xFF0000))

        url = LOFI_STREAMS.get(stream_key.lower(), DEFAULT_STREAM)
        await self._set(ctx.guild.id, channel.id, url)

        e = discord.Embed(
            title="<:zmusic:1504087777778602004>  24/7 Music Enabled!",
            color=0xFF0000)
        e.add_field(name="Channel", value=channel.mention, inline=True)
        e.add_field(name="Stream",  value=f"`{stream_key}`", inline=True)
        e.add_field(name="Available Streams",
                    value="`lofi` · `chill` · `beats`\n`>247 enable #ch lofi`",
                    inline=False)
        e.set_footer(text="Bot will auto-join and stay 24/7. Rejoins if kicked.")
        await ctx.send(embed=e)
        await self._join_and_stream(channel, url)

    @always_on_group.command(name="disable", aliases=["stop", "off"])
    @commands.guild_only()
    async def disable_247(self, ctx: commands.Context):
        if not (ctx.author.guild_permissions.manage_guild or
                ctx.author.id == OWNER_ID or
                ctx.author.id == ctx.guild.owner_id):
            return await ctx.send(embed=discord.Embed(
                description="❌ You need **Manage Server** permission.", color=0xFF0000))

        await self._disable(ctx.guild.id)
        vc = ctx.guild.voice_client
        if vc:
            await vc.disconnect(force=True)

        e = discord.Embed(
            description="✅ **24/7 Music** disabled. Bot has left the voice channel.",
            color=0xFF0000)
        await ctx.send(embed=e)

    @always_on_group.command(name="stream", aliases=["setstream"])
    @commands.guild_only()
    async def set_stream(self, ctx: commands.Context, stream_key: str = "lofi"):
        if not (ctx.author.guild_permissions.manage_guild or
                ctx.author.id == OWNER_ID or
                ctx.author.id == ctx.guild.owner_id):
            return await ctx.send(embed=discord.Embed(
                description="❌ You need **Manage Server** permission.", color=0xFF0000))

        row = await self._get(ctx.guild.id)
        if not row or not row[2]:
            return await ctx.send(embed=discord.Embed(
                description="❌ Enable 24/7 first with `>247 enable`", color=0xFF0000))

        url = LOFI_STREAMS.get(stream_key.lower(), DEFAULT_STREAM)
        await self._set(ctx.guild.id, row[0], url)

        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()

        channel = ctx.guild.get_channel(row[0])
        if channel:
            await self._join_and_stream(channel, url)

        await ctx.send(embed=discord.Embed(
            description=f"✅ Stream changed to **{stream_key}**.", color=0xFF0000))


async def setup(bot):
    await bot.add_cog(AlwaysOn(bot))
