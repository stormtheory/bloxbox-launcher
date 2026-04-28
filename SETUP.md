# Roblox Whitelist Launcher — Setup Guide

## How it works

- `bloxbox-launcher.py` — your son runs this. Shows only approved games as tiles.
  Clicking a game launches it directly, bypassing the Roblox homepage entirely.
- `admin.py` — you run this (with sudo). Add/remove approved games.
- `/etc/roblox_whitelist.json` — the approved games list. Root-owned, child can't edit it.

---

## First-time setup

### 1. Make sure Python 3 + tkinter is installed
```bash
sudo apt install python3 python3-tk
```

### 2. Initialise the config file
```bash
sudo python3 admin.py init
```

### 3. Add your first approved games
```bash
sudo python3 admin.py add
# Paste the Roblox game URL, e.g.:
# https://www.roblox.com/games/1818/Classic-Crossroads
```

### 4. Make sure your son's account has no sudo access
```bash
sudo deluser HISUSERNAME sudo
```

### 5. Create a desktop shortcut for the launcher on his account
Create a file at `/home/HISUSERNAME/Desktop/Games.desktop`:
```ini
[Desktop Entry]
Name=Game Launcher
Exec=python3 /opt/roblox_launcher/roblox_launcher.py
Icon=applications-games
Terminal=false
Type=Application
```

### 6. (Optional) Block direct Roblox access
To prevent him opening Roblox outside the launcher:
```bash
# Add to /etc/hosts (only useful as a soft barrier)
echo "127.0.0.1 roblox.com" | sudo tee -a /etc/hosts
echo "127.0.0.1 www.roblox.com" | sudo tee -a /etc/hosts
```

---

## Day-to-day usage

### List approved games
```bash
sudo python3 admin.py list
```

### Add a game your son has requested
```bash
sudo python3 admin.py add
```

### Remove a game
```bash
sudo python3 admin.py remove
```

---

## Example whitelist config (/etc/roblox_whitelist.json)
```json
{
  "games": [
    {
      "name": "Adopt Me!",
      "place_id": "920587943",
      "description": "Pet adoption & trading"
    },
    {
      "name": "Brookhaven",
      "place_id": "4924922222",
      "description": "Town roleplay"
    },
    {
      "name": "Natural Disaster Survival",
      "place_id": "189707",
      "description": "Survive disasters"
    }
  ]
}
```

---

## Notes

- Roblox on Linux requires **Sober** (the community Linux client): https://sober.vinegarhq.org
- The `roblox://` URI scheme must be registered — Sober handles this automatically on install.
- The launcher uses **only Python standard library** — no pip installs needed.
- To find a game's Place ID: open the game page on roblox.com, the number in the URL is the ID.
