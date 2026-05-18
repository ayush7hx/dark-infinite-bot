from __future__ import annotations
import discord
import aiosqlite
import asyncio
import os
import datetime
from discord.ext import commands
from core import Cog, zyrox

DB              = 'db/dmrelay.db'
RELAY_SERVER_ID = 1503964206150455357   # Emoji Server 2
LOG_SERVER_ID   = 1504060120492146708   # Emoji Server 1
OWNER_IDS       = [1258831252748894436, 870179991462236170, 1432771000629596225,
                   1382744437049790495, 1255716509443948648]

async def _open_db():
    os.makedirs('db', exist_ok=True)
    conn = await aiosqlite.connect(DB)
    await conn.execute('''CREATE TABLE IF NOT EXISTS relay_channels
        (channel_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT)''')
    await conn.execute('''CREATE TABLE IF NOT EXISTS pending_dms
        (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
         content TEXT, timestamp TEXT, relayed INTEGER DEFAULT 0)''')
    await conn.commit()
    return conn

class DmRelay(Cog):
    def __init__(self, bot: zyrox):
        self.bot = bot

    # ── DB helpers ─────────────────────────────────────────────────────────────

    async def _get_relay_channel_id(self, user_id: int):
        async with await _open_db() as db:
            async with db.execute('SELECT channel_id FROM relay_channels WHERE user_id=?', (user_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def _save_relay_channel(self, channel_id: int, user_id: int, username: str):
        async with await _open_db() as db:
            await db.execute('INSERT OR REPLACE INTO relay_channels (channel_id, user_id, username) VALUES (?,?,?)',
                             (channel_id, user_id, username))
            await db.commit()

    async def _get_user_from_channel(self, channel_id: int):
        async with await _open_db() as db:
            async with db.execute('SELECT user_id, username FROM relay_channels WHERE channel_id=?', (channel_id,)) as cur:
                row = await cur.fetchone()
                return (row[0], row[1]) if row else (None, None)

    async def _store_pending(self, user_id: int, username: str, content: str):
        async with await _open_db() as db:
            await db.execute('INSERT INTO pending_dms (user_id, username, content, timestamp) VALUES (?,?,?,?)',
                             (user_id, username, content, datetime.datetime.utcnow().isoformat()))
            await db.commit()

    async def _get_pending(self, user_id: int):
        async with await _open_db() as db:
            async with db.execute('SELECT id, content, timestamp FROM pending_dms WHERE user_id=? AND relayed=0',
                                  (user_id,)) as cur:
                rows = await cur.fetchall()
            if rows:
                ids = [r[0] for r in rows]
                await db.execute(f'UPDATE pending_dms SET relayed=1 WHERE id IN ({",".join("?" for _ in ids)})', ids)
                await db.commit()
            return rows

    async def _all_relay_channels(self):
        async with await _open_db() as db:
            async with db.execute('SELECT channel_id, user_id, username FROM relay_channels') as cur:
                return await cur.fetchall()

    # ── Get or create relay channel for user ──────────────────────────────────

    async def _get_or_create_relay_channel(self, user: discord.User) -> discord.TextChannel | None:
        guild = self.bot.get_guild(RELAY_SERVER_ID)
        if not guild:
            return None

        existing_id = await self._get_relay_channel_id(user.id)
        if existing_id:
            ch = guild.get_channel(existing_id)
            if ch:
                return ch

        # Find / create category
        category = discord.utils.get(guild.categories, name='📬 DM Relay')
        if not category:
            try:
                category = await guild.create_category('📬 DM Relay')
            except Exception:
                category = None

        # Safe channel name
        safe_name = ''.join(c if c.isalnum() or c in '-_' else '-' for c in user.name.lower())[:25]
        channel_name = f"dm-{safe_name}"

        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            try:
                channel = await guild.create_text_channel(
                    channel_name, category=category,
                    topic=f"DM relay for {user} | ID: {user.id}"
                )
                embed = discord.Embed(
                    title=f"📬 New DM Thread: {user}",
                    description=(
                        f"**User:** {user.mention} (`{user.id}`)\n"
                        f"**Username:** `{user.name}`\n\n"
                        "Is channel mein type karo → bot DM karega us user ko.\n"
                        "Uske DM bot pe aane par yahan dikhenge."
                    ),
                    color=0x5b8cff,
                    timestamp=datetime.datetime.utcnow()
                )
                if user.avatar:
                    embed.set_thumbnail(url=user.display_avatar.url)
                embed.set_footer(text="DARK INFINITE DM Relay")
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[DmRelay] Could not create channel: {e}")
                return None

        await self._save_relay_channel(channel.id, user.id, str(user))
        return channel

    # ── Listeners ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # ── Incoming DM → relay to server ──────────────────────────────────
        if isinstance(message.channel, discord.DMChannel):
            await self._handle_incoming_dm(message)
            return

        # ── Owner typing in relay channel → send DM back ───────────────────
        if (message.guild and
                message.guild.id == RELAY_SERVER_ID and
                message.author.id in OWNER_IDS and
                message.channel.name.startswith('dm-') and
                not message.content.startswith('>')):
            await self._handle_relay_reply(message)

    async def _handle_incoming_dm(self, message: discord.Message):
        # Store as pending (for offline catchup next time)
        await self._store_pending(message.author.id, str(message.author), message.content or '')

        try:
            channel = await self._get_or_create_relay_channel(message.author)
            if not channel:
                return

            embed = discord.Embed(
                description=message.content or '*[No text]*',
                color=0x5b8cff,
                timestamp=message.created_at
            )
            embed.set_author(
                name=f"📨 {message.author} ({message.author.id})",
                icon_url=message.author.display_avatar.url
            )

            if message.attachments:
                links = "\n".join(f"[{a.filename}]({a.url})" for a in message.attachments[:5])
                embed.add_field(name="📎 Attachments", value=links, inline=False)
            if message.stickers:
                embed.add_field(name="🎭 Sticker", value=message.stickers[0].name, inline=False)

            embed.set_footer(text="Reply here to send DM back · Owner only")
            await channel.send(embed=embed)

        except Exception as e:
            print(f"[DmRelay] Relay error: {e}")

    async def _handle_relay_reply(self, message: discord.Message):
        user_id, username = await self._get_user_from_channel(message.channel.id)
        if not user_id:
            await message.add_reaction('❓')
            return
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(message.content)
            await message.add_reaction('✅')
        except discord.Forbidden:
            await message.add_reaction('🚫')
            await message.reply("❌ Is user ne DMs band kar rakhe hain.", delete_after=5)
        except Exception as e:
            await message.add_reaction('❌')
            print(f"[DmRelay] Reply error: {e}")

    # ── On ready: catchup + notify ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(10)
        guild = self.bot.get_guild(RELAY_SERVER_ID)
        if not guild:
            return

        source = os.environ.get('BOT_SOURCE', 'Replit ☁️')
        rows = await self._all_relay_channels()

        for channel_id, user_id, username in rows:
            ch = guild.get_channel(channel_id)
            if not ch:
                continue
            # Post "bot online" notice
            try:
                notify = discord.Embed(
                    description=f"🟢 **Bot back online!** (`{source}`)\nPending messages check karo.",
                    color=0x3dd68c,
                    timestamp=datetime.datetime.utcnow()
                )
                await ch.send(embed=notify)

                # Relay any stored pending DMs
                pending = await self._get_pending(user_id)
                if pending:
                    for row_id, content, ts in pending[:10]:
                        if content:
                            e = discord.Embed(
                                description=f"*(Offline ke dauran aaya tha)*\n{content}",
                                color=0xffa500,
                                timestamp=datetime.datetime.fromisoformat(ts)
                            )
                            e.set_author(name=f"📨 {username} (offline msg)")
                            await ch.send(embed=e)
            except Exception as e:
                print(f"[DmRelay] On-ready notify error: {e}")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.command(name="dmrelaystatus", aliases=["relayinfo"])
    async def relay_status(self, ctx: commands.Context):
        if ctx.author.id not in OWNER_IDS:
            return
        guild = self.bot.get_guild(RELAY_SERVER_ID)
        rows  = await self._all_relay_channels()
        embed = discord.Embed(title="📬 DM Relay Status", color=0x5b8cff)
        embed.add_field(name="Relay Server", value=guild.name if guild else "❌ Not found", inline=True)
        embed.add_field(name="Active Threads", value=str(len(rows)), inline=True)
        embed.add_field(name="How to use", value=(
            "• Koi bhi DM kare → Server 2 mein uska channel banta hai\n"
            "• Us channel mein type karo → bot DM karega\n"
            "• Prefix (`>`) se shuru mat karo reply mein"
        ), inline=False)
        await ctx.reply(embed=embed)


async def setup(bot: zyrox):
    await bot.add_cog(DmRelay(bot))
