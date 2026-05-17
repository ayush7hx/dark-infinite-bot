import os
os.system("")
import sys

# ── Load .env file if present (for PC / local runs) ──────────────────────────
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path, 'r', encoding='utf-8') as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# ─── SINGLE INSTANCE LOCK (prevents multiple bots responding at once) ──────────
_LOCK_FILE = '/tmp/darkinfinite_bot.lock'
_lock_fd = None

def _acquire_lock():
    global _lock_fd
    if not _HAS_FCNTL:
        return
    _lock_fd = open(_LOCK_FILE, 'w')
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
    except IOError:
        print("Another bot instance is already running. Exiting to prevent duplicate responses.")
        sys.exit(0)

_acquire_lock()
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import threading
import traceback
from threading import Thread
import ctypes.util

# ─── Load libopus for voice support ───────────────────────────────────────────
def _load_opus():
    import discord as _discord
    if _discord.opus.is_loaded():
        return
    _opus_paths = [
        '/nix/store/0py9xncsn0s6vqxhvqblvhs2cqbb30s8-libopus-1.5.2/lib/libopus.so.0',
        'libopus.so.0',
        'libopus.so',
    ]
    for _path in _opus_paths:
        try:
            _discord.opus.load_opus(_path)
            print(f"[Voice] Loaded opus from {_path}")
            return
        except Exception:
            continue
    _sys_opus = ctypes.util.find_library('opus')
    if _sys_opus:
        try:
            _discord.opus.load_opus(_sys_opus)
            print(f"[Voice] Loaded opus: {_sys_opus}")
            return
        except Exception:
            pass
    print("[Voice] WARNING: libopus could not be loaded — voice features disabled.")

_load_opus()
# ──────────────────────────────────────────────────────────────────────────────
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

@app.route('/manifest.json')
def pwa_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def pwa_sw():
    resp = app.send_static_file('sw.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Content-Type'] = 'application/javascript'
    return resp

# ── PC-Lock: Only one PC bot runs at a time ───────────────────────────────────
import time as _time
_pc_lock: dict = {"holder": None, "expires": 0.0}

@app.route('/pc-lock/acquire')
def pc_lock_acquire():
    from flask import request, Response
    pc_id = request.args.get('id', 'unknown')
    now = _time.time()
    if (_pc_lock["holder"] is None
            or _pc_lock["expires"] < now
            or _pc_lock["holder"] == pc_id):
        _pc_lock["holder"] = pc_id
        _pc_lock["expires"] = now + 150
        return Response("OK", mimetype='text/plain')
    return Response(f"TAKEN:{_pc_lock['holder']}", mimetype='text/plain', status=409)

@app.route('/pc-lock/heartbeat')
def pc_lock_heartbeat():
    from flask import request, Response
    pc_id = request.args.get('id', 'unknown')
    if _pc_lock["holder"] == pc_id:
        _pc_lock["expires"] = _time.time() + 150
        return Response("OK", mimetype='text/plain')
    return Response("NOT_HOLDER", mimetype='text/plain', status=403)

@app.route('/pc-lock/release')
def pc_lock_release():
    from flask import request, Response
    pc_id = request.args.get('id', 'unknown')
    if _pc_lock["holder"] == pc_id:
        _pc_lock["holder"] = None
        _pc_lock["expires"] = 0.0
    return Response("OK", mimetype='text/plain')

@app.route('/pc-lock/status')
def pc_lock_status():
    from flask import Response
    if _pc_lock["holder"] and _pc_lock["expires"] > _time.time():
        return Response(f"LOCKED:{_pc_lock['holder']}", mimetype='text/plain')
    return Response("FREE", mimetype='text/plain')

# ── PC instances registry ─────────────────────────────────────────────────────
_pc_registry: dict = {}  # {pc_id: {"last_seen": float, "status": str}}

@app.route('/pc-lock/register')
def pc_lock_register():
    from flask import request, Response
    pc_id = request.args.get('id', 'unknown')
    status = request.args.get('status', 'active')
    _pc_registry[pc_id] = {"last_seen": _time.time(), "status": status, "name": pc_id}
    return Response("OK", mimetype='text/plain')

@app.route('/api/pc-status')
def api_pc_status():
    from flask import jsonify
    now = _time.time()
    result = []
    for pc_id, info in list(_pc_registry.items()):
        last_seen = info["last_seen"]
        age = now - last_seen
        online = age < 180  # 3 min timeout
        result.append({
            "id": pc_id,
            "name": pc_id,
            "status": "online" if online else "offline",
            "last_seen": int(age),
            "is_active": _pc_lock["holder"] == pc_id and _pc_lock["expires"] > now
        })
    # Sort: active first, then online, then offline
    result.sort(key=lambda x: (0 if x["is_active"] else 1 if x["status"]=="online" else 2))
    return jsonify(result)

@app.route('/version')
def bot_version():
    import os, hashlib
    try:
        files = ['CodeX.py', 'cogs/commands/owner.py', 'templates/dashboard.html']
        h = hashlib.md5(''.join(str(os.path.getmtime(f)) for f in files if os.path.exists(f)).encode()).hexdigest()[:8]
    except Exception:
        h = "unknown"
    from flask import Response
    return Response(h, mimetype='text/plain')

@app.route('/download/bot.zip')
def download_bot_zip():
    import zipfile, io, os
    from flask import Response
    buf = io.BytesIO()
    EXCLUDE_DIRS = {'.git', '__pycache__', 'node_modules', '.local', 'attached_assets'}
    EXCLUDE_EXT  = {'.pyc', '.pyo', '.log', '.db'}
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in files:
                if any(fname.endswith(e) for e in EXCLUDE_EXT):
                    continue
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, '.')
                try:
                    zf.write(fpath, arcname)
                except Exception:
                    pass
    buf.seek(0)
    return Response(buf.read(), mimetype='application/zip',
                    headers={'Content-Disposition': 'attachment; filename=DarkInfiniteBot.zip'})

@app.route('/setup.ps1')
def setup_ps1():
    import os as _os
    from flask import request, Response
    base_url = request.host_url.rstrip('/')
    bot_token = _os.getenv('TOKEN', '')
    groq_key  = _os.getenv('GROQ_API_KEY', '')

    # We build the PowerShell script as a plain string (no f-string braces confusion)
    # Python replaces only our markers: %%BASE_URL%% %%BOT_TOKEN%% %%GROQ_KEY%%
    template = r"""# ==============================================================
#  DARK INFINITE Bot — One-Command Auto Setup
#  Paste in PowerShell (Admin):
#  irm %%BASE_URL%%/setup.ps1 | iex
# ==============================================================
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$BotUrl   = '%%BASE_URL%%'
$BotToken = '%%BOT_TOKEN%%'
$GroqKey  = '%%GROQ_KEY%%'
$BotDir   = "$env:USERPROFILE\DarkInfiniteBot"

Write-Host ""
Write-Host "  ██████╗  █████╗ ██████╗ ██╗  ██╗" -ForegroundColor Red
Write-Host "  ██╔══██╗██╔══██╗██╔══██╗██║ ██╔╝" -ForegroundColor Red
Write-Host "  ██║  ██║███████║██████╔╝█████╔╝ " -ForegroundColor Red
Write-Host "  ██║  ██║██╔══██║██╔══██╗██╔═██╗ " -ForegroundColor Red
Write-Host "  ██████╔╝██║  ██║██║  ██║██║  ██╗" -ForegroundColor Red
Write-Host "  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝" -ForegroundColor DarkRed
Write-Host "       INFINITE  —  Auto Installer" -ForegroundColor DarkRed
Write-Host ""

# ── Step 1: Create folder ──────────────────────────────────────
New-Item -ItemType Directory -Force -Path $BotDir | Out-Null
Write-Host "[1/5] Folder ready: $BotDir" -ForegroundColor Green

# ── Step 2: Python check / install ────────────────────────────
$python = $null
foreach ($cmd in @('python','python3','py')) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { $python = $cmd; break }
}
if (-not $python) {
    Write-Host "[2/5] Python not found — downloading Python 3.11..." -ForegroundColor Yellow
    $pyInst = "$env:TEMP\python_installer.exe"
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile $pyInst -UseBasicParsing
    Start-Process $pyInst -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1' -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
    $python = 'python'
    Write-Host "[2/5] Python installed!" -ForegroundColor Green
} else {
    Write-Host "[2/5] Python OK  ($( & $python --version 2>&1 ))" -ForegroundColor Green
}

# ── Step 3: Download bot files ────────────────────────────────
Write-Host "[3/5] Downloading bot from Replit..." -ForegroundColor Yellow
$zip = "$env:TEMP\darkbot.zip"
Invoke-WebRequest "$BotUrl/download/bot.zip" -OutFile $zip -UseBasicParsing
Expand-Archive $zip -DestinationPath $BotDir -Force
Remove-Item $zip -Force

# Write environment variables to .env file (used by CodeX.py)
$envFile = "$BotDir\.env"
"TOKEN=$BotToken" | Set-Content $envFile -Encoding UTF8
"GROQ_API_KEY=$GroqKey" | Add-Content $envFile -Encoding UTF8

# Also set as persistent Windows env vars so they work even without .env
[System.Environment]::SetEnvironmentVariable('TOKEN',       $BotToken, 'User')
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY',$GroqKey,  'User')
$env:TOKEN        = $BotToken
$env:GROQ_API_KEY = $GroqKey

Write-Host "[3/5] Bot files + token saved!" -ForegroundColor Green

# ── Step 4: Install Python packages ───────────────────────────
Write-Host "[4/5] Installing packages (this may take a minute)..." -ForegroundColor Yellow
$req = "$BotDir\requirements.txt"
if (Test-Path $req) {
    & $python -m pip install -r $req -q --disable-pip-version-check
} else {
    & $python -m pip install "discord.py>=2.3" aiohttp flask groq aiosqlite colorama requests -q --disable-pip-version-check
}
Write-Host "[4/5] Packages installed!" -ForegroundColor Green

# ── Step 5: Auto-updater + Boot task ─────────────────────────
Write-Host "[5/5] Setting up auto-start + auto-update..." -ForegroundColor Yellow

# Auto-updater script
$updater = "$BotDir\auto_update.ps1"
Set-Content $updater -Encoding UTF8 -Value @"
`$BotUrl = '$BotUrl'
`$BotDir = '$BotDir'
`$env:TOKEN        = '$BotToken'
`$env:GROQ_API_KEY = '$GroqKey'
try {
    `$ver = (Invoke-WebRequest "`$BotUrl/version" -UseBasicParsing -TimeoutSec 8).Content.Trim()
    `$vf  = "`$BotDir\local_version.txt"
    `$old = if (Test-Path `$vf) { (Get-Content `$vf -Raw).Trim() } else { '' }
    if (`$ver -ne `$old) {
        `$z = "`$env:TEMP\darkbot_upd.zip"
        Invoke-WebRequest "`$BotUrl/download/bot.zip" -OutFile `$z -UseBasicParsing
        Expand-Archive `$z -DestinationPath `$BotDir -Force
        Remove-Item `$z -Force
        # Restore token after update
        "TOKEN=`$env:TOKEN`nGROQ_API_KEY=`$env:GROQ_API_KEY" | Set-Content "`$BotDir\.env" -Encoding UTF8
        `$ver | Set-Content `$vf
    }
} catch {}
"@

# Launcher batch — with Replit-online check + PC lock
$bat = "$BotDir\start_bot.bat"
# Generate a unique ID for this PC
$pcId = $env:COMPUTERNAME + "-" + (Get-Random -Maximum 9999)
Set-Content $bat -Encoding UTF8 -Value @"
@echo off
title DARK INFINITE Bot [%%COMPUTERNAME%%]
cd /d "$BotDir"
set "TOKEN=$BotToken"
set "GROQ_API_KEY=$GroqKey"

:: ── Check if Replit bot is already online ─────────────────────────────────
:check_replit
echo [%%TIME%%] Checking Replit status...
powershell -Command "try{`$r=(Invoke-WebRequest '$BotUrl/api/stats' -UseBasicParsing -TimeoutSec 8).Content;if(`$r -match 'commands'){exit 0}else{exit 1}}catch{exit 1}"
if %errorlevel%==0 (
    echo [%%TIME%%] Replit is ONLINE — standby mode. Checking again in 60s...
    timeout /t 60 /nobreak >nul
    goto check_replit
)

:: ── Try to acquire PC lock ─────────────────────────────────────────────────
:try_lock
echo [%%TIME%%] Replit offline. Trying to claim PC lock...
powershell -Command "try{`$r=(Invoke-WebRequest '$BotUrl/pc-lock/acquire?id=$pcId' -UseBasicParsing -TimeoutSec 8).Content;if(`$r -eq 'OK'){exit 0}else{exit 1}}catch{exit 1}"
if %errorlevel%==0 (
    echo [%%TIME%%] Lock acquired! Starting bot on this PC...
    goto start_bot
)
echo [%%TIME%%] Another PC already has the lock. Waiting 30s...
timeout /t 30 /nobreak >nul
goto check_replit

:: ── Run auto-update then launch bot ───────────────────────────────────────
:start_bot
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "$updater"

:: Register this PC in dashboard + Start heartbeat (keeps lock alive + updates dashboard)
start "" /b powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "while(`$true){try{Invoke-WebRequest '$BotUrl/pc-lock/heartbeat?id=$pcId' -UseBasicParsing -TimeoutSec 5|Out-Null}catch{};try{Invoke-WebRequest '$BotUrl/pc-lock/register?id=$pcId&status=active' -UseBasicParsing -TimeoutSec 5|Out-Null}catch{};Start-Sleep 60}"

$python CodeX.py

:: Bot stopped — release lock and restart check loop
powershell -Command "try{Invoke-WebRequest '$BotUrl/pc-lock/release?id=$pcId' -UseBasicParsing -TimeoutSec 5|Out-Null}catch{}"
echo [%%TIME%%] Bot stopped. Restarting check loop...
timeout /t 10 /nobreak >nul
goto check_replit
"@

# Windows Scheduled Task — runs at EVERY login (boot)
$act = New-ScheduledTaskAction `
    -Execute 'cmd.exe' `
    -Argument "/c `"$bat`""
$trg = New-ScheduledTaskTrigger -AtLogOn
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask `
    -TaskName   'DarkInfiniteBot' `
    -Action     $act `
    -Trigger    $trg `
    -Settings   $set `
    -RunLevel   Highest `
    -Force | Out-Null

# Also copy to Startup folder as fallback
$sf = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\DarkInfiniteBot.bat"
Copy-Item $bat $sf -Force

Write-Host "[5/5] Auto-start registered!" -ForegroundColor Green

Write-Host ""
Write-Host "  ✔  Setup Complete!" -ForegroundColor Green
Write-Host "     Bot folder : $BotDir" -ForegroundColor Cyan
Write-Host "     Token      : pre-filled (no input needed)" -ForegroundColor Cyan
Write-Host "     Auto-start : ON  (every PC login)" -ForegroundColor Cyan
Write-Host "     Auto-update: ON  (checks Replit on each start)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Starting bot now..." -ForegroundColor Yellow
Write-Host ""

Start-Process cmd.exe -ArgumentList "/k `"$bat`"" -WindowStyle Normal
"""

    script = template.replace('%%BASE_URL%%', base_url) \
                     .replace('%%BOT_TOKEN%%', bot_token) \
                     .replace('%%GROQ_KEY%%',  groq_key)

    return Response(script, mimetype='text/plain',
                    headers={'Content-Disposition': 'inline; filename=setup.ps1'})

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

    # ── Set bot avatar on startup ──────────────────────────────────────────
    try:
        _avatar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'bot_avatar.jpg')
        _avatar_hash_path = _avatar_path + '.hash'
        import hashlib as _hl
        with open(_avatar_path, 'rb') as _af:
            _avatar_bytes = _af.read()
        _new_hash = _hl.md5(_avatar_bytes).hexdigest()
        _old_hash = ''
        if os.path.exists(_avatar_hash_path):
            with open(_avatar_hash_path) as _hf:
                _old_hash = _hf.read().strip()
        if _new_hash != _old_hash:
            await client.user.edit(avatar=_avatar_bytes)
            with open(_avatar_hash_path, 'w') as _hf:
                _hf.write(_new_hash)
            print("[Avatar] Bot DP updated successfully!")
        else:
            print("[Avatar] DP already up to date.")
    except Exception as _ae:
        print(f"[Avatar] Could not update DP: {_ae}")


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
