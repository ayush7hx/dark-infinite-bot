#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo " ============================================="
echo "  DARK INFINITE Bot - Linux/Mac Launcher"
echo " ============================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python3 not found! Install it first."
    exit 1
fi

# Load or ask for TOKEN
if [ -f "token.txt" ]; then
    export TOKEN=$(cat token.txt)
    echo "[OK] Token loaded from token.txt"
else
    echo "[!] Enter your bot token:"
    read -r TOKEN
    echo "$TOKEN" > token.txt
    echo "[OK] Token saved to token.txt"
fi

# Install requirements once
if [ ! -f ".deps_installed" ]; then
    echo "[*] Installing requirements..."
    pip3 install -r requirements.txt -q
    touch .deps_installed
    echo "[OK] Done."
fi

echo ""
echo "[*] Bot starting... Press Ctrl+C to stop."
echo ""

while true; do
    # Check if Replit bot is online
    STATUS="OFFLINE"
    if [ -f "replit_url.txt" ]; then
        REPLIT_URL=$(cat replit_url.txt)
        if [ -n "$REPLIT_URL" ]; then
            HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$REPLIT_URL/api/stats" 2>/dev/null)
            if [ "$HTTP" = "200" ]; then
                STATUS="ONLINE"
            fi
        fi
    fi

    if [ "$STATUS" = "ONLINE" ]; then
        echo "[$(date +%T)] Replit bot ONLINE - sleeping 60s..."
        sleep 60
        continue
    fi

    echo "[$(date +%T)] Starting bot locally..."
    python3 CodeX.py

    echo ""
    echo "[$(date +%T)] Bot stopped. Restarting in 10s..."
    sleep 10
done
