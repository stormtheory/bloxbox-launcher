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
REQUESTS_PATH  = _config.REQUESTS_PATH
WINDOW_TITLE = _config.APP_WINDOW_TITLE_NAME

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


def save_request(url: str, note: str) -> bool:
    """
    Append a new game request to ~/.bloxbox_requests.json in the child's home.
    No special permissions needed — the child owns their own home directory.
    Returns True on success, False on failure.
    """
    requests = load_requests()
    requests.append({
        "url":       url.strip(),
        "note":      note.strip(),
        "timestamp": datetime.now().isoformat(timespec="seconds")
    })

    try:
        with open(REQUESTS_PATH, "w") as f:
            json.dump({"requests": requests}, f, indent=2)
        print(f"[launcher] Request saved → {REQUESTS_PATH}")
        return True
    except Exception as e:
        print(f"[launcher] Failed to save request: {e}")
        return False

# 
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

class RequestDialog(tk.Toplevel):
    """
    Modal dialog for submitting a game request.
    Child pastes a Roblox game URL and optionally writes a note.
    Saved to /etc/bloxbox_requests.json for parent to review with admin.py.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Request a Game")
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self.grab_set()  # Modal — blocks the main window while open
        self._build_ui()

        # Centre the dialog over the parent window
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

    def _build_ui(self):
        """Build the request form layout."""

        # Heading
        tk.Label(
            self, text="Request a New Game",
            font=("Georgia", 16, "bold"),
            bg=BG_COLOR, fg=TEXT_COLOR
        ).pack(padx=24, pady=(20, 2))

        tk.Label(
            self, text="Paste the Roblox game page URL below.",
            font=FONT_SMALL, bg=BG_COLOR, fg=SUBTEXT_COLOR
        ).pack(padx=24, pady=(0, 10))

        # Game URL field
        tk.Label(self, text="Game URL:", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w").pack(fill="x", padx=24, pady=(0, 2))
        self.url_entry = tk.Entry(
            self, font=FONT_SMALL,
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat", width=46
        )
        self.url_entry.pack(padx=24, ipady=6)

        # Optional note field
        tk.Label(self, text="Why do you want to play it? (optional):", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w").pack(fill="x", padx=24, pady=(10, 2))
        self.note_entry = tk.Entry(
            self, font=FONT_SMALL,
            bg="#252540", fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat", width=46
        )
        self.note_entry.pack(padx=24, ipady=6)

        # Submit / Cancel buttons
        btn_row = tk.Frame(self, bg=BG_COLOR)
        btn_row.pack(pady=20)

        tk.Button(
            btn_row, text="Send Request",
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
        """Validate inputs and save the request."""
        url  = self.url_entry.get().strip()
        note = self.note_entry.get().strip()

        # Must have a URL
        if not url:
            messagebox.showwarning("Missing URL", "Please paste the game URL.", parent=self)
            return

        # Must look like a roblox.com address
        if "roblox.com" not in url:
            messagebox.showwarning(
                "Invalid URL",
                "That doesn't look like a Roblox URL.\n"
                "Go to the game on roblox.com and copy the address bar.",
                parent=self
            )
            return

        # Try to save — may fail if file permissions aren't set up yet
        ok = save_request(url, note)

        if ok:
            messagebox.showinfo(
                "Request Sent! 🎮",
                "Your request has been saved.\nAsk a parent to review it!",
                parent=self
            )
            self.destroy()
        else:
            messagebox.showerror(
                "Could Not Save",
                "Permission error saving your request.\n"
                "Ask a parent to run:\n\n"
                f"  sudo chmod 0622 {REQUESTS_PATH}",
                parent=self
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
        """Open the game request modal."""
        RequestDialog(self)


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
