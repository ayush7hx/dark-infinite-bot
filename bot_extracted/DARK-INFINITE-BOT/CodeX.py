import os
os.system("")
import asyncio
import threading
import traceback
from threading import Thread
from datetime import datetime
import random
import time
import sqlite3

import aiohttp
import discord
from discord import Spotify
from discord.ext import commands, tasks

from core import Context
from core.Cog import Cog
from core.zyrox import zyrox
from utils.Tools import *
from utils.config import *

# ─── FLASK SETUP (all routes defined before server starts) ────────────────────
from flask import Flask, render_template, jsonify, request as flask_request
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'darkinfinite_dashboard_2025'

def _bot_ready():
    c = globals().get('client')
    return c is not None and c.is_ready()

@app.after_request
def add_headers(response):
    response.headers.pop('X-Frame-Options', None)
    response.headers.pop('Content-Security-Policy', None)
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Content-Security-Policy'] = "frame-ancestors *; default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;"
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = '*'
    response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
    response.headers['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
    response.headers['Cross-Origin-Opener-Policy'] = 'unsafe-none'
    return response

@app.route('/')
def home():
    return render_template('dashboard.html')

@app.route('/api/stats')
def api_stats():
    _dm_lock = globals().get('dm_lock')
    _dm_store = globals().get('dm_store', {})
    dm_count = 0
    if _dm_lock:
        with _dm_lock:
            dm_count = len(_dm_store)
    if not _bot_ready():
        return jsonify({'servers': 0, 'users': 0, 'commands': 0, 'dm_count': dm_count, 'servers_list': [], 'bot_name': 'DARK INFINITE', 'bot_avatar': None})
    c = globals()['client']
    servers_list = []
    for g in c.guilds:
        icon_url = str(g.icon.url) if g.icon else None
        servers_list.append({'id': str(g.id), 'name': g.name, 'members': g.member_count or 0, 'icon': icon_url})
    bot_avatar = str(c.user.display_avatar.url) if c.user else None
    return jsonify({
        'bot_name':    str(c.user) if c.user else 'DARK INFINITE',
        'bot_avatar':  bot_avatar,
        'servers':     len(c.guilds),
        'users':       sum(g.member_count or 0 for g in c.guilds),
        'commands':    len(list(c.commands)),
        'dm_count':    dm_count,
        'servers_list': servers_list
    })

@app.route('/api/servers')
def api_servers():
    if not _bot_ready():
        return jsonify([])
    c = globals()['client']
    result = []
    for g in c.guilds:
        icon_url = str(g.icon.url) if g.icon else None
        result.append({'id': str(g.id), 'name': g.name, 'members': g.member_count or 0, 'icon': icon_url})
    return jsonify(result)

@app.route('/api/dms')
def api_dms():
    _dm_lock = globals().get('dm_lock')
    _dm_store = globals().get('dm_store', {})
    if not _dm_lock:
        return jsonify([])
    with _dm_lock:
        result = []
        for uid, data in _dm_store.items():
            msgs      = data['messages']
            last_msg  = msgs[-1]['content'] if msgs else ''
            last_time = msgs[-1]['time'] if msgs else ''
            result.append({
                'user_id':      uid,
                'username':     data['user']['username'],
                'avatar':       data['user']['avatar'],
                'last_message': last_msg[:60],
                'last_time':    last_time
            })
    return jsonify(result)

@app.route('/api/dms/<user_id>')
def api_dm_conversation(user_id):
    _dm_lock = globals().get('dm_lock')
    _dm_store = globals().get('dm_store', {})
    if not _dm_lock:
        return jsonify([])
    with _dm_lock:
        data = _dm_store.get(user_id, {})
        return jsonify(data.get('messages', []))

@app.route('/api/send_dm', methods=['POST', 'OPTIONS'])
def api_send_dm():
    if flask_request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
    try:
        if not _bot_ready():
            return jsonify({'status': 'error', 'error': 'Bot not ready'}), 503
        c         = globals()['client']
        _dm_lock  = globals().get('dm_lock')
        _dm_store = globals().get('dm_store', {})
        body      = flask_request.get_json(force=True, silent=True) or {}
        user_id   = int(body.get('user_id', 0))
        content   = str(body.get('content', '')).strip()
        if not content or not user_id:
            return jsonify({'status': 'error', 'error': 'Missing user_id or content'}), 400

        async def do_send():
            user = await c.fetch_user(user_id)
            await user.send(content)

        future = asyncio.run_coroutine_threadsafe(do_send(), c.loop)
        future.result(timeout=15)

        uid      = str(user_id)
        msg_time = datetime.now().strftime('%H:%M')
        msg_obj  = {'content': content, 'direction': 'sent', 'time': msg_time, 'username': 'DARK INFINITE', 'avatar': None}
        if _dm_lock:
            with _dm_lock:
                user_info = (_dm_store.get(uid) or {}).get('user', {'id': uid, 'username': 'Unknown', 'avatar': None})
        _store_dm_fn = globals().get('_store_dm')
        if _store_dm_fn:
            _store_dm_fn(uid, user_info, msg_obj)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

def _run_flask():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    app.run(host='0.0.0.0', port=5000, threaded=True)

Thread(target=_run_flask, daemon=True).start()
# ──────────────────────────────────────────────────────────────────────────────

import jishaku
import cogs

os.environ["JISHAKU_NO_DM_TRACEBACK"] = "False"
os.environ["JISHAKU_HIDE"] = "True"
os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
os.environ["JISHAKU_FORCE_PAGINATOR"] = "True"

from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("TOKEN")

# --- Configuration ---
SERVER_COUNT_CHANNEL_ID = 1419729255977189467
USER_COUNT_CHANNEL_ID   = 1419729283861184632
LOG_CHANNEL_ID          = 1396794297386532978
BOT_OWNER_ID            = 1255716509443948648

# ─── PERSISTENT DM STORE (SQLite) ─────────────────────────────────────────────
os.makedirs('db', exist_ok=True)
DM_DB_PATH = 'db/dms.db'

def _init_dm_db():
    conn = sqlite3.connect(DM_DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS dm_users (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        avatar TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS dm_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        content TEXT,
        direction TEXT,
        time TEXT,
        username TEXT,
        avatar TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.commit()
    conn.close()

_init_dm_db()

# In-memory store (loaded from DB on start)
# {user_id_str: {'user': {id,username,avatar}, 'messages': [{content,direction,time,username,avatar}]}}
dm_store = {}
dm_lock  = threading.Lock()


def _load_dm_store_from_db():
    """Load all DMs from SQLite into memory on startup."""
    conn = sqlite3.connect(DM_DB_PATH)
    c = conn.cursor()
    # Load users
    c.execute('SELECT user_id, username, avatar FROM dm_users')
    users = c.fetchall()
    for uid, username, avatar in users:
        dm_store[uid] = {
            'user': {'id': uid, 'username': username, 'avatar': avatar},
            'messages': []
        }
    # Load messages
    c.execute('SELECT user_id, content, direction, time, username, avatar FROM dm_messages ORDER BY id ASC')
    for uid, content, direction, msg_time, username, avatar in c.fetchall():
        if uid in dm_store:
            dm_store[uid]['messages'].append({
                'content': content,
                'direction': direction,
                'time': msg_time,
                'username': username,
                'avatar': avatar
            })
    conn.close()
    print(f"[DM DB] Loaded {len(dm_store)} conversations from database.")

_load_dm_store_from_db()


def _save_dm_user(uid: str, username: str, avatar: str):
    """Upsert user info in DB (runs in thread)."""
    try:
        conn = sqlite3.connect(DM_DB_PATH)
        c = conn.cursor()
        c.execute(
            'INSERT OR REPLACE INTO dm_users (user_id, username, avatar) VALUES (?, ?, ?)',
            (uid, username, avatar)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DM DB] Save user error: {e}")


def _save_dm_message(uid: str, content: str, direction: str, msg_time: str, username: str, avatar: str):
    """Insert one message into DB (runs in thread)."""
    try:
        conn = sqlite3.connect(DM_DB_PATH)
        c = conn.cursor()
        c.execute(
            'INSERT INTO dm_messages (user_id, content, direction, time, username, avatar) VALUES (?, ?, ?, ?, ?, ?)',
            (uid, content, direction, msg_time, username, avatar)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DM DB] Save message error: {e}")


def _store_dm(uid: str, user_info: dict, msg: dict):
    """Thread-safe: add to memory + persist to DB."""
    with dm_lock:
        if uid not in dm_store:
            dm_store[uid] = {'user': user_info, 'messages': []}
        dm_store[uid]['messages'].append(msg)
    # Persist in background thread
    threading.Thread(
        target=_save_dm_user,
        args=(uid, user_info['username'], user_info.get('avatar')),
        daemon=True
    ).start()
    threading.Thread(
        target=_save_dm_message,
        args=(uid, msg['content'], msg['direction'], msg['time'], msg['username'], msg.get('avatar')),
        daemon=True
    ).start()


client = zyrox()
tree   = client.tree


# ─── DM LISTENER ──────────────────────────────────────────────────────────────
async def _on_dm_message(message: discord.Message):
    if message.guild is not None or message.author.bot:
        return
    uid    = str(message.author.id)
    avatar = str(message.author.display_avatar.url) if message.author.display_avatar else None
    user_info = {'id': uid, 'username': str(message.author), 'avatar': avatar}
    msg = {
        'content':   message.content or '[attachment/embed]',
        'direction': 'received',
        'time':      datetime.now().strftime('%H:%M'),
        'username':  str(message.author),
        'avatar':    avatar
    }
    _store_dm(uid, user_info, msg)

client.add_listener(_on_dm_message, 'on_message')


# ─── CATCH-UP: fetch offline DMs when bot restarts ────────────────────────────
async def _catch_up_offline_dms():
    """After bot is ready, fetch recent DMs from known users to catch offline messages."""
    await client.wait_until_ready()
    await asyncio.sleep(3)  # brief pause after ready
    with dm_lock:
        known_ids = list(dm_store.keys())

    for uid_str in known_ids:
        try:
            user = await client.fetch_user(int(uid_str))
            dm_channel = user.dm_channel or await user.create_dm()
            avatar = str(user.display_avatar.url) if user.display_avatar else None

            # Get last known message time to avoid duplicates
            with dm_lock:
                existing_msgs = dm_store.get(uid_str, {}).get('messages', [])

            # Fetch last 20 messages from the DM channel
            history = []
            async for msg in dm_channel.history(limit=20):
                history.append(msg)
            history.reverse()  # oldest first

            # Find new messages (those sent by user, not bot)
            existing_contents = set()
            with dm_lock:
                for m in dm_store.get(uid_str, {}).get('messages', []):
                    existing_contents.add((m['content'], m['direction'], m['time']))

            for hist_msg in history:
                if hist_msg.author.bot:
                    continue
                content = hist_msg.content or '[attachment/embed]'
                msg_time = hist_msg.created_at.strftime('%H:%M')
                # Only add if not already in store (simple dedup by content+time)
                with dm_lock:
                    already = any(
                        m['content'] == content and m['direction'] == 'received'
                        for m in dm_store.get(uid_str, {}).get('messages', [])
                        if m['time'] == msg_time
                    )
                if not already:
                    user_info = {'id': uid_str, 'username': str(hist_msg.author), 'avatar': avatar}
                    msg_obj = {
                        'content':   content,
                        'direction': 'received',
                        'time':      msg_time,
                        'username':  str(hist_msg.author),
                        'avatar':    avatar
                    }
                    _store_dm(uid_str, user_info, msg_obj)
        except Exception as e:
            pass  # silently skip, user may have blocked bot etc.

    print("[DM Catchup] Offline DM catch-up complete.")


# ─── BACKGROUND STATS ─────────────────────────────────────────────────────────
async def update_stats():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            servers = len(client.guilds)
            users   = sum(g.member_count for g in client.guilds if g.member_count)
            sc = client.get_channel(SERVER_COUNT_CHANNEL_ID)
            uc = client.get_channel(USER_COUNT_CHANNEL_ID)
            if sc:
                await sc.edit(name=f"Servers: {servers}")
            if uc:
                await uc.edit(name=f"Users: {users}")
        except Exception as e:
            print(f"Stats update error: {e}")
        await asyncio.sleep(600)


# ─── EVENTS ───────────────────────────────────────────────────────────────────
@client.event
async def on_ready():
    await client.wait_until_ready()
    print("""
        \033[1;31m
 ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
██║     ██║   ██║██║  ██║█████╗   ╚███╔╝ 
██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗ 
╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
        \033[0m
       """)
    print("Loaded & Online!")
    print(f"Logged in as: {client.user}")
    print(f"Connected to: {len(client.guilds)} guilds")
    print(f"Connected to: {len(client.users)} users")
    try:
        synced      = await client.tree.sync()
        all_commands = list(client.commands)
        print(f"Synced Total {len(all_commands)} Client Commands and {len(synced)} Slash Commands")
    except Exception as e:
        print(e)
    client.loop.create_task(update_stats())
    client.loop.create_task(_catch_up_offline_dms())


@client.event
async def on_guild_join(guild: discord.Guild):
    log_channel = client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"INF has been added to the server: **{guild.name}** (ID: `{guild.id}`)")


@client.event
async def on_command_completion(context: commands.Context) -> None:
    if context.author.id == 870179991462236170:
        return
    full_command_name = context.command.qualified_name
    executed_command  = str(full_command_name.split("\n")[0])
    guild_name        = context.guild.name if context.guild else "DM"
    print(f"[CMD] {executed_command} | {context.author} | {guild_name}")


# ─── UTILITY COMMANDS ─────────────────────────────────────────────────────────
@client.command(name='spotify')
async def spotify(ctx: Context, user: discord.Member = None):
    user = user or ctx.author
    sp   = next((a for a in user.activities if isinstance(a, Spotify)), None)
    if not sp:
        return await ctx.send(f"{user.name} is not listening to Spotify.")
    embed = discord.Embed(title=f"{user.name}'s Spotify", description=f"**Listening to:** {sp.title}", color=0x1DB954)
    embed.set_thumbnail(url=sp.album_cover_url)
    embed.add_field(name="Artist", value=sp.artist)
    embed.add_field(name="Album",  value=sp.album)
    embed.set_footer(text=f"Song started at {sp.created_at.strftime('%H:%M')}")
    await ctx.send(embed=embed)


@client.command(name='makeinvite', aliases=['createinvite', 'makeinv'])
@commands.is_owner()
async def make_invite(ctx: Context, guild_id: int = None):
    if guild_id is None:
        return await ctx.send("Please provide a Guild ID.")
    guild = client.get_guild(guild_id)
    if not guild:
        return await ctx.send("Invalid Guild ID. I am not in that server.")
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).create_instant_invite:
        try:
            inv = await guild.system_channel.create_invite(max_age=0, max_uses=0, unique=True)
            return await ctx.send(f"Invite for **{guild.name}**:\n{inv.url}")
        except:
            pass
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            try:
                inv = await channel.create_invite(max_age=0, max_uses=0, unique=True)
                return await ctx.send(f"Invite for **{guild.name}** (from #{channel.name}):\n{inv.url}")
            except:
                continue
    await ctx.send(f"I don't have 'Create Instant Invite' permission in **{guild.name}**.")


@client.command(name='create_hook', aliases=['makehook'])
@commands.has_permissions(administrator=True)
async def create_hook(ctx: Context, *, name: str = None):
    if not name:
        return await ctx.send("Please provide a name for the webhook.")
    try:
        wh = await ctx.channel.create_webhook(name=name, reason=f"Created by {ctx.author}")
        embed = discord.Embed(title="✅ Webhook Created", description=f"Webhook **{wh.name}** created.", color=0xFF0000)
        try:
            await ctx.author.send(f"Webhook URL for **{wh.name}**:\n||{wh.url}||", embed=embed)
            await ctx.send("Webhook created. URL sent to your DMs.")
        except:
            await ctx.send(f"Webhook created: **{wh.name}**\n||{wh.url}||")
    except discord.Forbidden:
        await ctx.send("I don't have permission to create webhooks here.")


@client.command(name='delete_hook', aliases=['delhook'])
@commands.has_permissions(administrator=True)
async def delete_hook(ctx: Context, webhook_url: str = None):
    if not webhook_url:
        return await ctx.send("Please provide the webhook URL.")
    try:
        async with aiohttp.ClientSession() as session:
            wh = await discord.Webhook.from_url(webhook_url, session=session)
            await wh.delete(reason=f"Deleted by {ctx.author}")
        await ctx.send("✅ Webhook deleted.")
    except (discord.NotFound, ValueError):
        await ctx.send("❌ Webhook not found or URL invalid.")


@client.command(name='list_hooks', aliases=['hooks'])
@commands.has_permissions(administrator=True)
async def list_hooks(ctx: Context):
    try:
        webhooks = await ctx.channel.webhooks()
        if not webhooks:
            return await ctx.send("No webhooks in this channel.")
        embed = discord.Embed(title=f"Webhooks in #{ctx.channel.name}", color=0xFF0000)
        embed.description = "\n".join([f"**{wh.name}** — `{wh.id}`" for wh in webhooks])
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("I don't have permission to view webhooks here.")


@client.command()
async def reaction(ctx: Context):
    emojis = ["🍪","🎉","🧋","🍒","🍑","💸","🌙","💕"]
    correct = random.choice(emojis)
    random.shuffle(emojis)
    embed = discord.Embed(title="Reaction Test", description="Get ready!", color=0xFF0000)
    message = await ctx.send(embed=embed)
    for emoji in emojis:
        await message.add_reaction(emoji)
    await asyncio.sleep(random.uniform(2.0, 7.0))
    embed.description = f"**GET THE {correct} EMOJI!**"
    await message.edit(embed=embed)
    start = time.time()
    def check(r, u):
        return r.message.id == message.id and str(r.emoji) == correct and u == ctx.author
    try:
        await client.wait_for("reaction_add", timeout=15.0, check=check)
        embed.description = f"Got it in **{time.time()-start:.2f}s**!"
        await message.edit(embed=embed)
    except asyncio.TimeoutError:
        embed.description = "Too slow! Timeout."
        await message.edit(embed=embed)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    async with client:
        os.system("clear")
        await client.load_extension("jishaku")
        max_retries = 5
        for attempt in range(max_retries):
            try:
                await client.start(TOKEN)
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    wait_time = min((2 ** attempt) + random.random(), 60)
                    print(f"Rate limited. Retrying in {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        else:
            raise Exception("Bot failed to start after retries.")

if __name__ == "__main__":
    asyncio.run(main())
