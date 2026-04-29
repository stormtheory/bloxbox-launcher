#!/usr/bin/env python3
"""
bloxbox-launcher.py — Kid-facing Roblox whitelist launcher.

Features:
  - Shows only parent-approved games as tiles with cover art thumbnails
  - Launches directly into the game via roblox:// URI (bypasses Roblox homepage)
  - Request button lets the child submit a new game URL for parent review
  - Requests are saved to /etc/bloxbox_requests.json (root-owned, parent reviews it)

Run as the child's user account (no sudo needed to launch).
The config and requests files are root-owned so only the parent can modify them.
"""

import json
import os
import subprocess
import tkinter as tk
from tkinter import messagebox
import urllib.request
import threading
import io
from pathlib import Path
from datetime import datetime
import importlib.util
import sys
import os
import time
import hashlib

try:
    import webview
except:
    print("Can't import webview.")

# Load system config from /etc — keeps config out of the app directory
_spec = importlib.util.spec_from_file_location("config", "/etc/bloxbox/config.py")
if _spec is None or _spec.loader is None:
    raise FileNotFoundError("System config not found at /etc/bloxbox/config.py")
    sys.exit(1)
_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config)

# Reference values directly
CONFIG_PATH = _config.CONFIG_PATH
FALLBACK_CONFIG = _config.FALLBACK_CONFIG
FALLBACK_REQUESTS = _config.FALLBACK_REQUESTS
CACHE_DIR = _config.CACHE_DIR
CHILD_USER = _config.CHILD_USER
REQUESTS_PATH  = _config.CLIENT_REQUESTS_PATH
WINDOW_TITLE = _config.APP_WINDOW_TITLE_NAME
LOCK_REQUEST_PIN_PASS_HASH = _config.LOCK_REQUEST_PIN_PASS_HASH
LOCK_REQUEST_GAMES = _config.LOCK_REQUEST_GAMES
ROBLOX_GAME_SEARCH_URL = 'https://www.roblox.com/charts?device=computer&country=us'

# ── Roblox API ────────────────────────────────────────────────────────────────
# Direct thumbnail endpoint — takes place ID, no universe ID lookup needed
THUMBNAIL_API = "https://thumbnails.roblox.com/v1/places/gameicons?placeIds={place_id}&size=256x256&format=Png"

# ── Visual settings ───────────────────────────────────────────────────────────
BG_COLOR      = "#0f0f1a"       # Dark navy background
CARD_COLOR    = "#1a1a2e"       # Slightly lighter card background
ACCENT_COLOR  = "#e94560"       # Red accent (play button)
REQUEST_COLOR = "#2a6496"       # Blue (request a game button)
TEXT_COLOR    = "#eaeaea"       # Light text
SUBTEXT_COLOR = "#888"          # Muted subtext
FONT_TITLE    = ("Georgia", 28, "bold")
FONT_CARD     = ("Georgia", 12, "bold")
FONT_SMALL    = ("Courier", 10)
FONT_BTN      = ("Georgia", 10, "bold")

# Card dimensions — tall enough for thumbnail + name + play button
CARD_WIDTH    = 200
CARD_HEIGHT   = 300
THUMB_SIZE    = 160             # Thumbnail display size in pixels
COLS          = 4               # Game cards per row

# ── Globals ────────────────────────────────────────────────────────────
# Global root window reference — lets background threads schedule UI calls safely
_tk_root_ref: tk.Tk | None = None

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> list:
    """
    Load the approved games list from the root-owned config file.
    Falls back to home directory config if /etc version is missing (dev/test mode).
    Returns a list of game dicts: [{name, place_id, description}, ...]
    """
    for path in [CONFIG_PATH, str(FALLBACK_CONFIG)]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f).get("games", [])
            except (json.JSONDecodeError, PermissionError) as e:
                print(f"[launcher] Could not read config {path}: {e}")
    return []


def load_requests() -> list:
    """
    Load pending game requests from the child's home directory.
    File: ~/.bloxbox_requests.json
    Returns a list of request dicts: [{url, note, timestamp}, ...]
    """
    path = Path(REQUESTS_PATH)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f).get("requests", [])
        except (json.JSONDecodeError, PermissionError) as e:
            print(f"[launcher] Could not read requests file: {e}")
    return []

def save_request(place_id: str, game_name: str, note: str, url: str = "") -> bool:
    print(f"[bloxbox] save_request called: {place_id} / {game_name}")
    print(f"[bloxbox] REQUESTS_PATH: {REQUESTS_PATH}")
    print(f"[bloxbox] File exists: {os.path.exists(REQUESTS_PATH)}")
    
    requests = load_requests()
    print(f"[bloxbox] Existing requests: {len(requests)}")
    
    requests.append({
        "place_id":  place_id.strip(),
        "game_name": game_name.strip(),
        "url":       url.strip(),
        "note":      note.strip(),
        "timestamp": datetime.now().isoformat(timespec="seconds")
    })

    try:
        with open(REQUESTS_PATH, "w") as f:
            json.dump({"requests": requests}, f, indent=2)
        print(f"[bloxbox] Request saved → {REQUESTS_PATH}")
        return True
    except Exception as e:
        print(f"[bloxbox] Failed to save request: {e}")
        return False


def verify_pin(input_pin: str) -> bool:
    """Verify input PIN against hash generated by bash sha256sum."""
    if LOCK_REQUEST_GAMES:
        return hashlib.sha256(input_pin.encode()).hexdigest() == LOCK_REQUEST_PIN_PASS_HASH
    else:
        return True
    
def terminateSober():
    result =subprocess.run("pkill sober", shell=True, check=False)
    print(f"[bloxbox] pkill exit code: {result.returncode}")

# ── Thumbnail fetching ────────────────────────────────────────────────────────

def fetch_thumbnail_url(place_id: str) -> str | None:
    """
    Fetch the thumbnail image URL directly from the Roblox gameicons endpoint.
    No universe ID lookup needed — place ID is sufficient.
    Returns the CDN image URL string, or None on failure.
    """
    url = THUMBNAIL_API.format(place_id=place_id)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data  = json.loads(resp.read())
            items = data.get("data", [])
            if items and items[0].get("imageUrl"):
                return items[0]["imageUrl"]
    except Exception as e:
        print(f"[launcher] Thumbnail URL fetch failed for place {place_id}: {e}")
    return None

def fetch_game_name(place_id: str) -> str:
    """
    Fetch the game name from Roblox using the economy assets API.
    Returns the game name string, or None on failure.
    """
    url = f"https://economy.roblox.com/v2/assets/{place_id}/details"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return data.get("Name")
    except Exception as e:
        print(f"[bloxbox] Game name lookup failed for {place_id}: {e}")
    return None

def fetch_thumbnail_image(place_id: str):
    """
    Full pipeline: place ID → thumbnail URL → PIL Image.

    Uses a disk cache to avoid re-fetching on every app launch.
    Cache lives at: ~/.cache/bloxbox_launcher/thumbnails/<place_id>.png

    Returns a PIL Image object, or None if anything fails.
    Pillow (PIL) must be installed: pip3 install Pillow --break-system-packages
    """
    # ── Check disk cache first to avoid unnecessary API calls ────────────
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{place_id}.png"

    if cache_file.exists():
        try:
            from PIL import Image
            return Image.open(cache_file)
        except Exception as e:
            print(f"[launcher] Cache read failed for {place_id}: {e}")
            cache_file.unlink(missing_ok=True)  # Purge corrupt cache file

    # ── Cache miss — fetch directly using place ID ────────────────────────
    thumb_url = fetch_thumbnail_url(place_id)
    if not thumb_url:
        return None

    try:
        from PIL import Image
        # Download the raw PNG bytes
        with urllib.request.urlopen(thumb_url, timeout=8) as resp:
            img_data = resp.read()

        # Write to cache for next time
        with open(cache_file, "wb") as f:
            f.write(img_data)

        return Image.open(io.BytesIO(img_data))

    except ImportError:
        print("[launcher] Pillow not installed — install with: pip3 install Pillow --break-system-packages")
        return None
    except Exception as e:
        print(f"[launcher] Thumbnail download failed for place {place_id}: {e}")
        return None

def _monitor_sober_log(proc: subprocess.Popen, game_name: str):
    """
    Background thread: reads Sober's log line by line watching for errors.
    On error: kills Sober, shows a friendly popup on the main thread.
    """
    ERROR_PATTERNS = {
        "App not yet initialized, returning from game": (
            "Login / Session Error",
            "Roblox kicked back to the home screen before the game loaded.\n\n"
            "Fix: Open Sober manually, log in again, then try Bloxbox."
        ),
        "HTTP error code:`nil`": (
            "Network / Auth Error",
            "Roblox reported a network or authentication error.\n\n"
            "Check your internet connection and try again."
        ),
        "524": (
            "Error 524 — Server Timeout",
            "The Roblox game server didn't respond in time.\n\n"
            "This is a temporary Roblox issue — wait a minute and try again."
        ),
        "SessionReporterState_GameExitRequested": (
            "Kicked by Server",
            "The Roblox server ended the session before the game started.\n\n"
            "The server may be full or restarting — try again shortly."
        ),
    }

    detected_error = None

    try:
        for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            for pattern, error_info in ERROR_PATTERNS.items():
                if pattern in line:
                    detected_error = error_info
                    print(f"[bloxbox] Error detected: {pattern}")
                    break
            if detected_error:
                break
    except Exception as e:
        print(f"[bloxbox] Monitor thread error: {e}")
        return

    if detected_error:
        title, message = detected_error
        terminateSober()

        _tk_root_ref.after(0, lambda: messagebox.showerror(
            f"⚠️  {title} — {game_name}", message
        ))

# ── Game launching ────────────────────────────────────────────────────────────

def launch_game(place_id: str, game_name: str):
    """
    Launch a Roblox game directly, bypassing the Roblox homepage entirely.

    Launch strategy (tried in order):
      1. Flatpak Sober with full roblox:// URI — confirmed working on Linux Mint 22.3
      2. xdg-open roblox:// URI — fallback if Sober registered the URI handler
      3. Friendly error dialog with install instructions

    Sober (org.vinegarhq.Sober) is the community Linux Roblox client.
    Vinegar (org.vinegarhq.Vinegar) does NOT support direct place launching.
    """
    place_id = str(place_id).strip()
    uri      = f"roblox://experiences/start?placeId={place_id}"
    print(f"[launcher] Launching '{game_name}' → {uri}")

    # ── Strategy 1: Flatpak Sober ─────────────────────────────────────────
    # Pass the full roblox:// URI — bare place ID is silently ignored by Sober.
    # Popen (not run) so the UI stays responsive while the game loads.
    try:
        proc = subprocess.Popen(
            ["flatpak", "run", "org.vinegarhq.Sober", uri],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        threading.Thread(
            target=_monitor_sober_log,
            args=(proc, game_name),
            daemon=True
        ).start()
        return  # Handed off to Sober — done
    except FileNotFoundError:
        print("[launcher] flatpak not found, falling back to xdg-open...")

    # ── Strategy 2: xdg-open roblox:// URI ───────────────────────────────
    # Works if Sober registered the roblox:// protocol handler during install
    try:
        subprocess.Popen(["xdg-open", uri])
        return
    except FileNotFoundError:
        pass

    # ── Strategy 3: Nothing worked ────────────────────────────────────────
    messagebox.showerror(
        "Launch Failed",
        f"Could not launch '{game_name}'.\n\n"
        "Make sure Sober is installed:\n"
        "  flatpak install flathub org.vinegarhq.Sober"
    )


# ── Request dialog ────────────────────────────────────────────────────────────

class RequestDialog:
    """
    Browser-based game request dialog using pywebview.
    Opens a restricted browser window locked to roblox.com only.
    Child browses to a game, hits 'Request This Game' button injected
    into the page — captures the place ID from the URL automatically.
    No launch capability — request only.
    pywebview runs on the main thread — Tkinter is hidden while browser is open.
    """

    def __init__(self, parent):
        self.parent  = parent
        self.window  = None
        # Pending request data set by JS handler — processed after webview closes
        self._pending_place_id  = None
        self._pending_game_name = None

        # Hide Tkinter while webview runs on the main thread
        self.parent.withdraw()
        self._open_browser()
        # Restore Tkinter after webview closes
        self.parent.deiconify()

        # If a game was requested, show the confirm dialog
        if self._pending_place_id:
            self._confirm_request(self._pending_place_id, self._pending_game_name, "")

    def _get_inject_js(self) -> str:
        """
        Returns JavaScript injected into every Roblox page.
        Injects a floating 'Request This Game' button that only appears
        on game pages (/games/<id>/...). On click, calls Python API
        with the place ID and game name — no launch capability.
        """
        return """
        (function() {
            // Create the floating request button
            var btn = document.createElement('div');
            btn.id = 'bloxbox-request-btn';
            btn.innerHTML = '＋ Request This Game';
            btn.style.cssText = `
                position: fixed;
                bottom: 30px;
                right: 30px;
                background: #2a6496;
                color: white;
                padding: 14px 22px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                z-index: 99999;
                box-shadow: 0 4px 12px rgba(0,0,0,0.4);
                font-family: Georgia, serif;
                user-select: none;
                display: none;
            `;

            // Show button only on game pages, hide on all other pages
            function updateButtonVisibility() {
                var match = window.location.pathname.match(/\\/games\\/(\\d+)/);
                if (match) {
                    btn.style.display = 'block';
                    btn.dataset.placeId = match[1];
                } else {
                    btn.style.display = 'none';
                }
            }

            // Handle the request button click — send to Python, no launching
            btn.addEventListener('click', function() {
                var placeId = btn.dataset.placeId;
                var gameName = document.title
                    .replace(' - Roblox', '')
                    .replace(' on Roblox', '')
                    .trim();

                if (placeId) {
                    // Disable button immediately to prevent double-clicks
                    btn.style.background = '#1e4d6b';
                    btn.innerHTML = '✅ Requested!';

                    // Call Python handler
                    window.pywebview.api.request_game(placeId, gameName);
                }
            });

            document.body.appendChild(btn);

            // Poll for URL changes — Roblox is a SPA, no full page reloads
            var lastUrl = window.location.href;
            setInterval(function() {
                if (window.location.href !== lastUrl) {
                    lastUrl = window.location.href;
                    updateButtonVisibility();
                }
            }, 500);

            updateButtonVisibility();
        })();
        """

    def _open_browser(self):
        """
        Open the pywebview browser window on the main thread.
        Starts on Roblox charts page — no JS injection needed.
        Polls the current URL every 500ms looking for a game page.
        When a game URL is detected, shows a Tkinter overlay bar
        at the bottom of the screen with a Request button.
        Blocks until the window is closed.
        """
        os.environ["PYWEBVIEW_GUI"] = "gtk"

        dialog      = self
        last_url    = [None]       # Mutable so inner thread can update it
        overlay_win = [None]       # Tkinter overlay window reference
        detecting   = [True]       # Flag to stop polling when window closes

        def poll_url():
            """
            Background thread: polls current URL every 500ms.
            Shows/hides the Tkinter request overlay based on whether
            we're on a game page (/games/<id>/).
            """
            import re
            while detecting[0]:
                try:
                    url = dialog.window.get_current_url()
                    if url and url != last_url[0]:
                        last_url[0] = url
                        print(f"[bloxbox] URL changed → {url}")

                        # Check if this is a game page
                        match = re.search(r"/games/(\d+)", url)
                        if match:
                            place_id = match.group(1)
                            # Small delay — Roblox SPA may still be transitioning URLs
                            _tk_root_ref.after(300, lambda pid=place_id: show_overlay(pid, url))
                        else:
                            _tk_root_ref.after(0, hide_overlay)

                except Exception as e:
                    print(f"[bloxbox] URL poll error: {e}")

                time.sleep(0.5)

        def show_overlay(place_id: str, url: str):
            """
            Show a request bar docked to the bottom of the main launcher window.
            Replaces any existing overlay.
            """
            hide_overlay()  # Remove any existing overlay first

            win = tk.Toplevel(dialog.parent)
            win.overrideredirect(True)   # No window chrome — bare overlay
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.95)
            win.configure(bg="#1a1a2e")
            overlay_win[0] = win

            # Position at the bottom of the main launcher window
            dialog.parent.update_idletasks()
            main_x = dialog.parent.winfo_x()
            main_y = dialog.parent.winfo_y()
            main_w = dialog.parent.winfo_width()
            main_h = dialog.parent.winfo_height()

            bar_h = 60
            # Dock to bottom edge of the launcher window, full width
            win.geometry(f"{main_w}x{bar_h}+{main_x}+{main_y + main_h - bar_h}")

            # Left side — game detected label with name lookup
            tk.Label(
                win,
                text=f"🎮  Fetching game name...",
                font=("Georgia", 11),
                bg="#1a1a2e", fg="#eaeaea",
                name="game_label"
            ).pack(side="left", padx=20)

            # Fetch game name in background and update the label
            name_label = win.children["game_label"]
            def load_name():
                game_name = fetch_game_name(place_id) or f"Place ID: {place_id}"
                # Check widget still exists before updating — thread may outlive the window
                try:
                    if win.winfo_exists() and name_label.winfo_exists():
                        win.after(0, lambda: name_label.config(
                            text=f"🎮  {game_name}  •  ID: {place_id}"
                        ))
                except Exception:
                    pass
            threading.Thread(target=load_name, daemon=True).start()

            # Right side — cancel button
            tk.Button(
                win,
                text="✕",
                font=("Georgia", 11, "bold"),
                bg="#333", fg="#aaa",
                activebackground="#444",
                relief="flat", cursor="hand2",
                padx=10, pady=8,
                command=hide_overlay
            ).pack(side="right", padx=(0, 10))

            # Right side — request button
            tk.Button(
                win,
                text="＋ Request This Game",
                font=("Georgia", 11, "bold"),
                bg="#2a6496", fg="white",
                activebackground="#1e4d6b",
                relief="flat", cursor="hand2",
                padx=14, pady=8,
                command=lambda: on_request(place_id, fetch_game_name(place_id), url)
            ).pack(side="right", padx=(0, 6))

            # Re-dock if the main window is moved or resized
            def track_main_window():
                while overlay_win[0] and detecting[0]:
                    try:
                        dialog.parent.update_idletasks()
                        mx = dialog.parent.winfo_x()
                        my = dialog.parent.winfo_y()
                        mw = dialog.parent.winfo_width()
                        mh = dialog.parent.winfo_height()
                        win.geometry(f"{mw}x{bar_h}+{mx}+{my + mh - bar_h}")
                    except Exception:
                        break
                    time.sleep(0.3)

            threading.Thread(target=track_main_window, daemon=True).start()

        def hide_overlay():
            """Destroy the overlay bar if it exists."""
            if overlay_win[0]:
                try:
                    overlay_win[0].destroy()
                except Exception:
                    pass
                overlay_win[0] = None

        def on_request(place_id: str, game_name: str, url: str):
            print(f"[bloxbox] Request triggered for place ID: {place_id}")
            detecting[0] = False
            hide_overlay()
            dialog._pending_place_id  = place_id
            dialog._pending_game_name = fetch_game_name(place_id)
            # Schedule confirm dialog on Tkinter main thread BEFORE destroying webview
            # — don't wait for __init__ to resume, call it directly
            _tk_root_ref.after(100, lambda: dialog._confirm_request(place_id, game_name, url))
            # Destroy all webview windows
            for w in webview.windows:
                w.destroy()

        def on_loaded():
            """Start URL polling once the first page loads."""
            threading.Thread(target=poll_url, daemon=True).start()

        # Create the browser window — starts on Roblox charts filtered to PC games
        self.window = webview.create_window(
            title     = "Bloxbox — Browse & Request Games",
            url       = ROBLOX_GAME_SEARCH_URL,
            width     = 1100,
            height    = 700,
            resizable = True,
            on_top    = False,   # Overlay handles topmost — browser stays normal
            js_api    = None,    # No JS injection needed — URL polling only
        )

        # Wire up the loaded event to start polling
        self.window.events.loaded += on_loaded

        # Start webview — blocks until window is closed
        webview.start(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Cleanup when browser closes
        detecting[0] = False
        hide_overlay()

    def _confirm_request(self, place_id: str, game_name: str, url: str):
        """
        Tkinter confirmation dialog shown after child picks a game in the browser.
        Shows thumbnail preview, optional note field, and submit/cancel buttons.
        Shown after webview has closed and Tkinter is restored.
        """
        print(f"[bloxbox] _confirm_request called: {place_id} / {game_name}")
        win = tk.Toplevel(self.parent)
        win.title("Confirm Request")
        win.configure(bg=BG_COLOR)
        win.resizable(False, False)
        win.grab_set()

        # Centre over parent window
        win.update_idletasks()
        px = self.parent.winfo_x() + (self.parent.winfo_width()  - 440) // 2
        py = self.parent.winfo_y() + (self.parent.winfo_height() - 380) // 2
        win.geometry(f"440x380+{px}+{py}")

        # ── Heading ───────────────────────────────────────────────────────
        tk.Label(
            win, text="Confirm Game Request",
            font=("Georgia", 16, "bold"),
            bg=BG_COLOR, fg=TEXT_COLOR
        ).pack(pady=(20, 4))

        # ── Thumbnail ─────────────────────────────────────────────────────
        thumb_label = tk.Label(
            win, text="⏳",
            font=("Georgia", 28),
            bg=BG_COLOR, fg=SUBTEXT_COLOR
        )
        thumb_label.pack()

        # ── Game name ─────────────────────────────────────────────────────
        tk.Label(
            win, text=game_name,
            font=FONT_CARD,
            bg=BG_COLOR, fg=TEXT_COLOR,
            wraplength=380, justify="center"
        ).pack(pady=(4, 0))

        # Place ID shown in small muted text for transparency
        tk.Label(
            win, text=f"Place ID: {place_id} \n {url}",
            font=("Courier", 9),
            bg=BG_COLOR, fg="#444"
        ).pack()

        # ── Optional note ─────────────────────────────────────────────────
        tk.Label(
            win, text="Why do you want to play it? (optional):",
            font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w"
        ).pack(fill="x", padx=24, pady=(10, 2))

        note_entry = tk.Entry(
            win, font=FONT_SMALL,
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat", width=40
        )
        note_entry.pack(padx=24, ipady=6)

        # ── Load thumbnail in background ──────────────────────────────────
        def load_thumb():
            thumb_url = fetch_thumbnail_url(place_id)
            if not thumb_url:
                win.after(0, lambda: thumb_label.config(text="🎮"))
                return
            try:
                from PIL import Image, ImageTk
                with urllib.request.urlopen(thumb_url, timeout=8) as r:
                    img   = Image.open(io.BytesIO(r.read()))
                    img   = img.resize((100, 100), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    GameCard._image_refs.append(photo)  # Prevent GC
                    win.after(0, lambda: thumb_label.config(image=photo, text=""))
            except Exception:
                win.after(0, lambda: thumb_label.config(text="🎮"))

        threading.Thread(target=load_thumb, daemon=True).start()

        # ── Submit / Cancel buttons ───────────────────────────────────────
        def on_submit():
            ok = save_request(
                place_id  = place_id,
                game_name = game_name,
                note      = note_entry.get().strip(),
                url       = url
            )
            win.destroy()
            if ok:
                messagebox.showinfo(
                    "Request Sent! 🎮",
                    f"'{game_name}' has been requested.\n"
                    "Ask a parent to review it!"
                )
            else:
                messagebox.showerror(
                    "Could Not Save",
                    "Permission error saving your request.\n"
                    "Ask a parent to check the requests file."
                )

        btn_row = tk.Frame(win, bg=BG_COLOR)
        btn_row.pack(pady=16)

        tk.Button(
            btn_row, text="Send Request",
            font=FONT_BTN,
            bg=REQUEST_COLOR, fg="white",
            activebackground="#1e4d6b",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=on_submit
        ).pack(side="left", padx=8)

        tk.Button(
            btn_row, text="Cancel",
            font=FONT_BTN,
            bg="#333", fg=TEXT_COLOR,
            activebackground="#444",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=win.destroy
        ).pack(side="left", padx=8)

        # Wait for this dialog to close before returning
        win.wait_window()
        
        
        
class RequestDialogFallback(tk.Toplevel):
    """
    Fallback request dialog for when pywebview is not installed.
    Opens roblox.com/charts in Firefox so child can find games,
    then child enters the place ID from the URL bar manually.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Request a Game")
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self.grab_set()

        self.fetched_place_id  = None
        self.fetched_game_name = None

        self._build_ui()

        # Centre over parent
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

    def _build_ui(self):
        """Place ID entry + lookup preview + submit."""

        tk.Label(
            self, text="Request a New Game",
            font=("Georgia", 16, "bold"),
            bg=BG_COLOR, fg=TEXT_COLOR
        ).pack(padx=24, pady=(20, 2))

        tk.Label(
            self,
            text="Find a game in the browser that just opened.\n"
                 "Copy the number from the URL bar:\n"
                 "roblox.com/games/185655149/... → enter 185655149",
            font=FONT_SMALL, bg=BG_COLOR, fg=SUBTEXT_COLOR,
            justify="center"
        ).pack(padx=24, pady=(0, 10))

        # ── Place ID entry + lookup ───────────────────────────────────────
        entry_row = tk.Frame(self, bg=BG_COLOR)
        entry_row.pack(padx=24, fill="x")

        self.id_entry = tk.Entry(
            entry_row, font=FONT_SMALL,
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat", width=30
        )
        self.id_entry.pack(side="left", ipady=6, padx=(0, 8))

        tk.Button(
            entry_row, text="Look Up",
            font=FONT_BTN,
            bg=REQUEST_COLOR, fg="white",
            activebackground="#1e4d6b",
            relief="flat", cursor="hand2",
            padx=12, pady=5,
            command=self._on_lookup
        ).pack(side="left")

        # ── Preview area ──────────────────────────────────────────────────
        self.thumb_label = tk.Label(
            self, text="", font=("Georgia", 28),
            bg=BG_COLOR, fg=SUBTEXT_COLOR
        )
        self.thumb_label.pack(pady=(10, 2))

        self.name_label = tk.Label(
            self, text="", font=FONT_CARD,
            bg=BG_COLOR, fg=TEXT_COLOR,
            wraplength=380, justify="center"
        )
        self.name_label.pack()

        self.status_label = tk.Label(
            self, text="", font=FONT_SMALL,
            bg=BG_COLOR, fg=SUBTEXT_COLOR
        )
        self.status_label.pack(pady=(4, 0))

        # ── Optional note ─────────────────────────────────────────────────
        tk.Label(
            self, text="Why do you want to play it? (optional):",
            font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w"
        ).pack(fill="x", padx=24, pady=(10, 2))

        self.note_entry = tk.Entry(
            self, font=FONT_SMALL,
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat", width=46
        )
        self.note_entry.pack(padx=24, ipady=6)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=BG_COLOR)
        btn_row.pack(pady=20)

        # Disabled until lookup succeeds
        self.submit_btn = tk.Button(
            btn_row, text="Send Request",
            font=FONT_BTN,
            bg="#444", fg="#888",
            relief="flat", cursor="arrow",
            padx=16, pady=6,
            state="disabled",
            command=self._on_submit
        )
        self.submit_btn.pack(side="left", padx=8)

        tk.Button(
            btn_row, text="Cancel",
            font=FONT_BTN,
            bg="#333", fg=TEXT_COLOR,
            activebackground="#444",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=self.destroy
        ).pack(side="left", padx=8)

    def _on_lookup(self):
        """Validate place ID and kick off background lookup."""
        place_id = self.id_entry.get().strip()

        if not place_id.isdigit():
            self.status_label.config(
                text="⚠️  Place ID must be a number.",
                fg=ACCENT_COLOR
            )
            return

        self.status_label.config(text="Looking up game...", fg=SUBTEXT_COLOR)
        self.name_label.config(text="")
        self.thumb_label.config(text="⏳", image="")
        self.submit_btn.config(state="disabled", bg="#444", fg="#888", cursor="arrow")

        threading.Thread(target=self._do_lookup, args=(place_id,), daemon=True).start()

    def _do_lookup(self, place_id: str):
        """Background thread: fetch name and thumbnail."""
        thumb_url = fetch_thumbnail_url(place_id)
        game_name = fetch_game_name(place_id)
        self.after(0, lambda: self._show_preview(place_id, game_name, thumb_url))

    def _show_preview(self, place_id: str, game_name: str, thumb_url: str):
        """Update preview area and enable submit if lookup succeeded."""
        if not game_name and not thumb_url:
            self.status_label.config(
                text="⚠️  Game not found. Check the Place ID.",
                fg=ACCENT_COLOR
            )
            self.thumb_label.config(text="❓", image="")
            return

        self.fetched_place_id  = place_id
        self.fetched_game_name = game_name or f"Game {place_id}"
        self.name_label.config(text=self.fetched_game_name)

        if thumb_url:
            threading.Thread(
                target=self._load_thumb, args=(thumb_url,), daemon=True
            ).start()
        else:
            self.thumb_label.config(text="🎮", image="")

        self.status_label.config(text="✅  Game found!", fg="#4caf50")
        self.submit_btn.config(
            state="normal",
            bg=REQUEST_COLOR, fg="white", cursor="hand2"
        )

    def _load_thumb(self, thumb_url: str):
        """Background thread: download and display thumbnail."""
        try:
            from PIL import Image, ImageTk
            with urllib.request.urlopen(thumb_url, timeout=8) as r:
                img   = Image.open(io.BytesIO(r.read()))
                img   = img.resize((100, 100), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                GameCard._image_refs.append(photo)
                self.after(0, lambda: self.thumb_label.config(image=photo, text=""))
        except Exception:
            self.after(0, lambda: self.thumb_label.config(text="🎮", image=""))

    def _on_submit(self):
        """Save the request."""
        if not self.fetched_place_id:
            return

        ok = save_request(
            place_id  = self.fetched_place_id,
            game_name = self.fetched_game_name,
            note      = self.note_entry.get().strip(),
            url       = ""
        )
        self.destroy()
        if ok:
            messagebox.showinfo(
                "Request Sent! 🎮",
                f"'{self.fetched_game_name}' has been requested.\n"
                "Ask a parent to review it!"
            )
        else:
            messagebox.showerror(
                "Could Not Save",
                "Permission error saving your request.\n"
                "Ask a parent to check the requests file."
            )


# ── Game card ─────────────────────────────────────────────────────────────────

class GameCard(tk.Frame):
    """
    A single game tile in the launcher grid.
    Shows game thumbnail (loaded async in background), name, and Play button.
    Hover highlights the card background.
    """

    # Keep PhotoImage references at class level — Tkinter garbage-collects them
    # if only held in local scope, causing images to disappear.
    _image_refs: list = []

    def __init__(self, parent, game: dict, **kwargs):
        super().__init__(
            parent,
            bg=CARD_COLOR,
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
            relief="flat",
            **kwargs
        )
        self.game        = game
        self.thumb_label = None
        self.pack_propagate(False)  # Lock card to fixed dimensions
        self._build_ui()
        self._bind_hover()

        # Kick off thumbnail fetch in background — keeps UI snappy
        threading.Thread(target=self._load_thumbnail, daemon=True).start()

    def _build_ui(self):
        """Build card layout: thumbnail → name → play button."""

        # Thumbnail placeholder shown while image is loading
        self.thumb_label = tk.Label(
            self,
            text="⏳",
            font=("Georgia", 28),
            bg=CARD_COLOR, fg=SUBTEXT_COLOR,
            width=THUMB_SIZE, height=8   # height in text units (approx)
        )
        self.thumb_label.pack(pady=(10, 4))

        # Game name — truncated with wraplength if too long
        tk.Label(
            self,
            text=self.game.get("name", "Unknown"),
            font=FONT_CARD,
            bg=CARD_COLOR, fg=TEXT_COLOR,
            wraplength=CARD_WIDTH - 16,
            justify="center"
        ).pack(pady=(2, 0))

        # Play button — triggers direct game launch
        tk.Button(
            self,
            text="▶  Play",
            font=FONT_BTN,
            bg=ACCENT_COLOR, fg="white",
            activebackground="#c73652",
            activeforeground="white",
            relief="flat", cursor="hand2",
            padx=14, pady=5,
            command=self._on_launch
        ).pack(pady=8)

    def _load_thumbnail(self):
        """
        Background thread: fetch thumbnail image and update the card.
        Uses after() to update the Tkinter label from the main thread
        — touching Tkinter widgets directly from threads causes crashes.
        """
        place_id = self.game.get("place_id", "")
        img      = fetch_thumbnail_image(place_id)

        if img is None:
            # No thumbnail available — swap spinner for a game controller emoji
            self.after(0, lambda: self._set_placeholder("🎮"))
            return

        try:
            from PIL import Image, ImageTk
            # Resize to fit the card neatly
            img   = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)

            # Hold a reference at class level to prevent garbage collection
            GameCard._image_refs.append(photo)

            # Schedule the UI update on the main thread
            self.after(0, lambda: self._set_thumbnail(photo))

        except ImportError:
            # Pillow not installed — show fallback emoji
            self.after(0, lambda: self._set_placeholder("🎮"))
        except Exception as e:
            print(f"[launcher] Thumbnail render failed for {place_id}: {e}")
            self.after(0, lambda: self._set_placeholder("🎮"))

    def _set_thumbnail(self, photo):
        """Swap the loading placeholder with the actual thumbnail image."""
        if self.thumb_label and self.thumb_label.winfo_exists():
            self.thumb_label.config(
                image=photo, text="",
                width=THUMB_SIZE, height=THUMB_SIZE
            )

    def _set_placeholder(self, emoji: str):
        """Replace the spinner with a fallback emoji (Pillow missing or API failed)."""
        if self.thumb_label and self.thumb_label.winfo_exists():
            self.thumb_label.config(text=emoji, font=("Georgia", 32))

    def _on_launch(self):
        """Play button click handler."""
        result = subprocess.run("ps -ef | grep -v grep | grep sober", shell=True)
        if result.returncode == 0:
            terminateSober()

        launch_game(
            place_id=self.game.get("place_id", ""),
            game_name=self.game.get("name", "Game")
        )

    def _bind_hover(self):
        """Highlight card on mouse-over with a slightly lighter background."""
        hover_bg = "#252540"

        def on_enter(_):
            self.config(bg=hover_bg)
            for w in self.winfo_children():
                try: w.config(bg=hover_bg)
                except tk.TclError: pass

        def on_leave(_):
            self.config(bg=CARD_COLOR)
            for w in self.winfo_children():
                try: w.config(bg=CARD_COLOR)
                except tk.TclError: pass

        # Bind to the frame and all immediate children
        for widget in [self, *self.winfo_children()]:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

# ── Passcode request ──────────────────────────────────────────────────────
class PinDialog(tk.Toplevel):
    """
    Modal PIN entry dialog shown before the request flow starts.
    Verifies the entered PIN against the stored hash via verify_pin().
    Returns self.verified = True if correct, False if cancelled or wrong.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Enter Passcode")
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self.grab_set()

        self.verified = False   # Set to True only on correct PIN

        self._build_ui()

        # Centre over parent
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

        # Bind Enter key to submit
        self.bind("<Return>", lambda e: self._on_submit())

        # Focus the PIN entry immediately
        self.after(100, self.pin_entry.focus_set)

        # Block until dialog is closed
        self.wait_window()

    def _build_ui(self):
        """Build PIN entry form."""

        tk.Label(
            self, text="🔒  Enter Passcode to Request a Game",
            font=("Georgia", 14, "bold"),
            bg=BG_COLOR, fg=TEXT_COLOR
        ).pack(padx=30, pady=(24, 6))

        tk.Label(
            self,
            text="Ask a parent if you don't know the Passcode.",
            font=FONT_SMALL, bg=BG_COLOR, fg=SUBTEXT_COLOR
        ).pack(padx=30, pady=(0, 14))

        # PIN entry — masked with *
        self.pin_entry = tk.Entry(
            self,
            font=("Georgia", 18),
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat",
            width=12,
            show="●",        # Mask the PIN characters
            justify="center"
        )
        self.pin_entry.pack(padx=30, ipady=8)

        # Error label — hidden until a wrong PIN is entered
        self.error_label = tk.Label(
            self, text="",
            font=FONT_SMALL, bg=BG_COLOR, fg=ACCENT_COLOR
        )
        self.error_label.pack(pady=(6, 0))

        # Buttons
        btn_row = tk.Frame(self, bg=BG_COLOR)
        btn_row.pack(pady=20)

        tk.Button(
            btn_row, text="Confirm",
            font=FONT_BTN,
            bg=REQUEST_COLOR, fg="white",
            activebackground="#1e4d6b",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=self._on_submit
        ).pack(side="left", padx=8)

        tk.Button(
            btn_row, text="Cancel",
            font=FONT_BTN,
            bg="#333", fg=TEXT_COLOR,
            activebackground="#444",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=self.destroy
        ).pack(side="left", padx=8)

    def _on_submit(self):
        """Verify the entered PIN against the stored hash."""
        pin = self.pin_entry.get().strip()

        if not pin:
            self.error_label.config(text="⚠️  Please enter a PIN.")
            return

        if verify_pin(pin):
            # Correct — set verified and close
            self.verified = True
            self.destroy()
        else:
            # Wrong — clear entry, show error, let them try again
            self.pin_entry.delete(0, tk.END)
            self.error_label.config(text="❌  Incorrect PIN. Try again.")
            self.pin_entry.focus_set()


# ── Main launcher window ──────────────────────────────────────────────────────

class LauncherApp(tk.Tk):
    """
    Main launcher window.
    Header with title + Request button, then a scrollable grid of game cards.
    """

    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.configure(bg=BG_COLOR)
        self.resizable(True, True)
        global _tk_root_ref
        _tk_root_ref = self
        self._build_ui()

    def _build_ui(self):
        """Assemble header + scrollable game grid."""

        # ── Header bar ────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG_COLOR)
        header.pack(fill="x", padx=30, pady=(24, 8))

        # Title (left side)
        tk.Label(
            header,
            text="🎮 BloxBox Game Launcher",
            font=FONT_TITLE,
            bg=BG_COLOR, fg=TEXT_COLOR
        ).pack(side="left")

        tk.Label(
            header,
            text="Approved games only",
            font=FONT_SMALL,
            bg=BG_COLOR, fg=SUBTEXT_COLOR
        ).pack(side="left", padx=16, pady=6)

        # Request button (right side) — child uses this to ask for new games
        tk.Button(
            header,
            text="＋  Request a Game",
            font=FONT_BTN,
            bg=REQUEST_COLOR, fg="white",
            activebackground="#1e4d6b",
            relief="flat", cursor="hand2",
            padx=14, pady=6,
            command=self._open_request_dialog
        ).pack(side="right")

        # ── Scrollable game grid ──────────────────────────────────────────────
        canvas_frame = tk.Frame(self, bg=BG_COLOR)
        canvas_frame.pack(fill="both", expand=True, padx=20, pady=10)

        canvas    = tk.Canvas(canvas_frame, bg=BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Inner frame holds the actual game cards
        self.grid_frame = tk.Frame(canvas, bg=BG_COLOR)
        canvas_win      = canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        # Keep scroll region updated as cards are added
        self.grid_frame.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        # Keep inner frame width in sync with canvas width
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))

        # Mouse wheel scrolling — Linux uses Button-4/5 events
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        canvas.bind_all("<Button-4>",   lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>",   lambda e: canvas.yview_scroll(1,  "units"))

        self._populate_grid()

    def _populate_grid(self):
        """Load approved games and render a card for each."""
        games = load_config()

        if not games:
            # Empty state — point child to the request button
            tk.Label(
                self.grid_frame,
                text="No games approved yet.\nUse '＋ Request a Game' above!",
                font=("Georgia", 16),
                bg=BG_COLOR, fg=SUBTEXT_COLOR,
                justify="center"
            ).grid(row=0, column=0, padx=40, pady=80)
            return

        # Render cards in a COLS-wide grid
        for idx, game in enumerate(games):
            GameCard(self.grid_frame, game).grid(
                row=idx // COLS,
                column=idx % COLS,  # column position within the COLS-wide grid
                padx=12, pady=12, sticky="nw"
            )

    def _open_request_dialog(self):
        """
        Open the game request dialog.
        First verifies the PIN — only proceeds if correct.
        Uses browser dialog if pywebview available, fallback otherwise.
        """
        # Gate on PIN verification before showing request dialog
        pin_dialog = PinDialog(self)
        if not pin_dialog.verified:
            return  # Cancelled or wrong PIN — do nothing
        try:
            import webview
            # pywebview is available — use the full browser experience
            RequestDialog(self)
        except ImportError:
            # pywebview not installed — fall back to place ID dialog
            # Open Firefox to roblox charts so child can browse and find place IDs
            try:
                subprocess.Popen(
                    ["firefox", ROBLOX_GAME_SEARCH_URL],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                # Firefox not installed — try default browser
                try:
                    subprocess.Popen(
                        ["xdg-open", ROBLOX_GAME_SEARCH_URL],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass  # No browser available — just show the dialog
            RequestDialogFallback(self)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Warn early if Pillow is missing — thumbnails will show emoji fallbacks
    try:
        import PIL
    except ImportError:
        print("[launcher] ⚠️  Pillow not installed — thumbnails disabled.")
        print("[launcher]    Fix: pip3 install Pillow --break-system-packages")

    app = LauncherApp()
    app.geometry("940x680")
    app.mainloop()
