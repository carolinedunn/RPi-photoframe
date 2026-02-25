#!/usr/bin/env python3
"""
Raspberry Pi Photo Slideshow
Syncs photos from a public Dropbox shared folder link — no Dropbox account needed on the Pi.
Displays fullscreen with date/time and weather overlays.
"""

import os
import sys
import random
import threading
import time
import datetime
import urllib.request
import urllib.parse
import json
import subprocess

# ============================================================
#  USER CONFIGURATION — edit these settings to your liking
# ============================================================

# Paste your Dropbox shared folder "Copy link" URL here
DROPBOX_SHARED_LINK   = "https://www.dropbox.com/scl/fo/rfzp5hjvw0fvcnpvzlw5d/AJaNy1ZrwcfQb-Uw-6zK5pA?rlkey=hh6tes6472vzxilrc88ed655m&st=xxtlixh4&dl=0"

# Local folder where photos are cached on the Pi
IMAGE_FOLDER          = os.path.expanduser("~/slideshow_cache/")

# How often to check Dropbox for new/removed photos (seconds)
DROPBOX_SYNC_INTERVAL = 300   # 5 minutes

SLIDE_DURATION        = 30          # seconds per image
TRANSITION            = "crossfade" # "crossfade" or "cut"
IMAGE_ORDER           = "random"    # "random" or "sequential"

LATITUDE              = 33.749      # Your latitude  (e.g. Atlanta, GA)
LONGITUDE             = -84.388     # Your longitude (e.g. Atlanta, GA)
TEMP_UNIT             = "F"         # "F" for Fahrenheit, "C" for Celsius

WEATHER_REFRESH       = 600         # seconds between weather fetches (10 min)
CROSSFADE_STEPS       = 30          # frames in crossfade
OVERLAY_FONT_SIZE     = 22
OVERLAY_PADDING       = 8           # px inside overlay boxes
OVERLAY_MARGIN        = 10          # px from screen edge
OVERLAY_COLOR         = (50, 50, 50, 128)     # RGBA dark gray 50% opacity
FONT_PATH             = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ============================================================
#  END OF USER CONFIGURATION
# ============================================================

import pygame

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif"}


# ---------------------------------------------------------------
#  Dropbox shared folder sync  (no API key / no daemon needed)
# ---------------------------------------------------------------

def _rlkey_from_url(url):
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return params.get("rlkey", [None])[0]


def fetch_dropbox_file_list(shared_link):
    """
    Use the Dropbox API v2 files/list_folder endpoint with a shared_link
    argument — works with any public shared folder, no auth token needed.
    Returns list of {name, tag} dicts, or None on error.
    """
    rlkey = _rlkey_from_url(shared_link)
    shared_link_obj = {"url": shared_link}
    if rlkey:
        shared_link_obj["link_permissions"] = {}   # required field when rlkey present

    body = json.dumps({
        "path": "",
        "shared_link": shared_link_obj,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.dropboxapi.com/2/files/list_folder",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode()).get("entries", [])
    except urllib.error.HTTPError as e:
        print(f"[Dropbox] list_folder HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[Dropbox] list_folder error: {e}")
    return None


def build_download_url(shared_folder_link, filename):
    """
    Construct a direct-download URL for a file inside a public shared folder.
    Pattern: swap the folder URL base, append /filename?dl=1
    """
    rlkey = _rlkey_from_url(shared_folder_link)
    base = shared_folder_link.split("?")[0].rstrip("/")
    url = base + "/" + urllib.parse.quote(filename) + "?dl=1"
    if rlkey:
        url += "&rlkey=" + rlkey
    return url


def sync_dropbox_folder(shared_link, local_folder):
    """
    Download new images from the Dropbox shared folder to local_folder.
    Deletes local files that were removed from the remote folder.
    Returns True on success, False on failure.
    """
    os.makedirs(local_folder, exist_ok=True)

    entries = fetch_dropbox_file_list(shared_link)
    if entries is None:
        return False

    remote_images = {
        e["name"]: e
        for e in entries
        if e.get(".tag") == "file"
        and os.path.splitext(e["name"])[1].lower() in SUPPORTED_EXTS
    }

    if not remote_images:
        print("[Dropbox] Folder exists but contains no supported image files.")
        return False

    print(f"[Dropbox] {len(remote_images)} image(s) found remotely.")

    # Download missing files
    for name in remote_images:
        local_path = os.path.join(local_folder, name)
        if not os.path.exists(local_path):
            url = build_download_url(shared_link, name)
            print(f"[Dropbox] Downloading: {name}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    content = resp.read()
                with open(local_path, "wb") as f:
                    f.write(content)
                print(f"[Dropbox] Saved: {name} ({len(content)//1024} KB)")
            except Exception as e:
                print(f"[Dropbox] Failed to download {name}: {e}")

    # Remove files deleted from the remote folder
    for fname in os.listdir(local_folder):
        if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTS:
            if fname not in remote_images:
                print(f"[Dropbox] Removing {fname} (deleted remotely)")
                try:
                    os.remove(os.path.join(local_folder, fname))
                except Exception:
                    pass

    return True


class DropboxSyncThread(threading.Thread):
    def __init__(self, shared_link, local_folder, interval):
        super().__init__(daemon=True)
        self.shared_link = shared_link
        self.local_folder = local_folder
        self.interval = interval
        self.synced_ok = False

    def run(self):
        while True:
            print("[Dropbox] Starting sync...")
            self.synced_ok = sync_dropbox_folder(self.shared_link, self.local_folder)
            status = "complete" if self.synced_ok else "FAILED (will retry)"
            print(f"[Dropbox] Sync {status}.")
            time.sleep(self.interval)


# ---------------------------------------------------------------
#  Weather (Open-Meteo, no API key needed)
# ---------------------------------------------------------------

WMO_CODES = {
    0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Heavy Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Heavy Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm+Hail", 99: "Thunderstorm+Hail",
}

def fetch_weather():
    unit_param = "fahrenheit" if TEMP_UNIT.upper() == "F" else "celsius"
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current_weather=true&temperature_unit={unit_param}"
        f"&wind_speed_unit=mph&timezone=auto"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            cw = json.loads(resp.read().decode())["current_weather"]
        sym = "°F" if TEMP_UNIT.upper() == "F" else "°C"
        return {
            "line1": f"{cw['temperature']:.0f}{sym}  {WMO_CODES.get(int(cw['weathercode']), 'Unknown')}",
            "line2": f"Wind: {cw['windspeed']:.0f} mph",
        }
    except Exception:
        return None


class WeatherThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._data = None
        self._lock = threading.Lock()

    def run(self):
        while True:
            result = fetch_weather()
            with self._lock:
                self._data = result
            time.sleep(WEATHER_REFRESH)

    def get(self):
        with self._lock:
            return self._data


# ---------------------------------------------------------------
#  Image helpers
# ---------------------------------------------------------------

def load_image_list(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    )


def scale_to_fit(surface, tw, th):
    iw, ih = surface.get_size()
    s = min(tw / iw, th / ih)
    nw, nh = int(iw * s), int(ih * s)
    scaled = pygame.transform.smoothscale(surface, (nw, nh))
    canvas = pygame.Surface((tw, th))
    canvas.fill((0, 0, 0))
    canvas.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def load_and_scale(path, w, h):
    try:
        return scale_to_fit(pygame.image.load(path).convert(), w, h)
    except Exception as e:
        print(f"[Image] Cannot load {path}: {e}")
        return None


# ---------------------------------------------------------------
#  Overlay drawing
# ---------------------------------------------------------------

def get_font(size=OVERLAY_FONT_SIZE):
    if os.path.exists(FONT_PATH):
        return pygame.font.Font(FONT_PATH, size)
    return pygame.font.SysFont("sans", size)


def draw_overlay_box(screen, lines, x, y, anchor="topleft"):
    font = get_font()
    pad = OVERLAY_PADDING
    rendered = [font.render(ln, True, (255, 255, 255)) for ln in lines]
    text_w = max(r.get_width() for r in rendered)
    lh = rendered[0].get_height()
    box_w = text_w + pad * 2
    box_h = lh * len(rendered) + 4 * (len(rendered) - 1) + pad * 2

    if   anchor == "topleft":     bx, by = x, y
    elif anchor == "bottomleft":  bx, by = x, y - box_h
    elif anchor == "topright":    bx, by = x - box_w, y
    elif anchor == "bottomright": bx, by = x - box_w, y - box_h
    else:                         bx, by = x, y

    surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    pygame.draw.rect(surf, OVERLAY_COLOR, (0, 0, box_w, box_h), border_radius=8)
    screen.blit(surf, (bx, by))

    ty = by + pad
    for r in rendered:
        screen.blit(r, (bx + pad, ty))
        ty += lh + 4


def draw_overlays(screen, weather):
    sw, sh = screen.get_size()
    m = OVERLAY_MARGIN
    now = datetime.datetime.now()
    draw_overlay_box(
        screen,
        [f"{now.strftime('%A, %B %-d')}  ·  {now.strftime('%-I:%M %p')}"],
        m, sh - m, anchor="bottomleft"
    )
    draw_overlay_box(
        screen,
        ["Weather unavailable"] if weather is None else [weather["line1"], weather["line2"]],
        sw - m, m, anchor="topright"
    )


# ---------------------------------------------------------------
#  Status screen (shown while syncing / no photos)
# ---------------------------------------------------------------

def draw_status(screen, lines):
    screen.fill((0, 0, 0))
    font = get_font(24)
    lh = 36
    total = len(lines) * lh
    sy = (screen.get_height() - total) // 2
    for i, line in enumerate(lines):
        surf = font.render(line, True, (180, 180, 180))
        rect = surf.get_rect(center=(screen.get_width() // 2, sy + i * lh))
        screen.blit(surf, rect)


# ---------------------------------------------------------------
#  Crossfade
# ---------------------------------------------------------------

def crossfade(screen, old_surf, new_surf, overlay_fn=None):
    clock = pygame.time.Clock()
    for i in range(1, CROSSFADE_STEPS + 1):
        screen.blit(old_surf, (0, 0))
        new_surf.set_alpha(int(255 * i / CROSSFADE_STEPS))
        screen.blit(new_surf, (0, 0))
        new_surf.set_alpha(255)
        if overlay_fn:
            overlay_fn(screen)
        pygame.display.flip()
        clock.tick(30)


# ---------------------------------------------------------------
#  Screen blanking
# ---------------------------------------------------------------

def disable_screen_blanking():
    for cmd in [["xset", "s", "off"], ["xset", "s", "noblank"], ["xset", "-dpms"]]:
        try:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0:
                # Non-fatal — some Pi display configs don't support -dpms
                print(f"[xset] Non-fatal: {' '.join(cmd)} -> {r.stderr.decode().strip()}")
        except FileNotFoundError:
            print("[xset] Not installed — screen blanking may still occur.")


# ---------------------------------------------------------------
#  Main loop
# ---------------------------------------------------------------

def main():
    disable_screen_blanking()

    pygame.init()
    pygame.mouse.set_visible(False)

    info = pygame.display.Info()
    SW, SH = info.current_w, info.current_h
    screen = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN)
    pygame.display.set_caption("Slideshow")
    clock = pygame.time.Clock()

    # Start background threads
    weather_thread = WeatherThread()
    weather_thread.start()

    dropbox_thread = DropboxSyncThread(DROPBOX_SHARED_LINK, IMAGE_FOLDER, DROPBOX_SYNC_INTERVAL)
    dropbox_thread.start()

    image_list   = []
    index        = 0
    current_surf = None
    slide_start  = time.time()

    running = True
    while running:
        now     = time.time()
        weather = weather_thread.get()

        # --- Events ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if   event.key == pygame.K_ESCAPE: running = False
                elif event.key == pygame.K_RIGHT:  slide_start = now - SLIDE_DURATION
                elif event.key == pygame.K_LEFT:
                    index = max(0, index - 2)
                    slide_start = now - SLIDE_DURATION
            elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
                tx = (event.x * SW) if event.type == pygame.FINGERUP else event.pos[0]
                if tx < SW / 3:
                    index = max(0, index - 2)
                    slide_start = now - SLIDE_DURATION
                elif tx > 2 * SW / 3:
                    slide_start = now - SLIDE_DURATION

        fresh_list = load_image_list(IMAGE_FOLDER)

        # --- First load after sync completes ---
        if current_surf is None and fresh_list:
            image_list = fresh_list
            if IMAGE_ORDER == "random":
                random.shuffle(image_list)
            current_surf = load_and_scale(image_list[0], SW, SH)
            index = 0
            slide_start = time.time()

        # --- Advance slide ---
        if now - slide_start >= SLIDE_DURATION and current_surf is not None:
            image_list = fresh_list
            if IMAGE_ORDER == "random":
                random.shuffle(image_list)
            if image_list:
                index = (index + 1) % len(image_list)
                old_surf = current_surf
                new_surf = load_and_scale(image_list[index], SW, SH)
                if new_surf and old_surf and TRANSITION == "crossfade":
                    crossfade(screen, old_surf, new_surf, overlay_fn=lambda s: draw_overlays(s, weather))
                current_surf = new_surf or old_surf
            slide_start = time.time()

        # --- Draw ---
        if current_surf:
            screen.blit(current_surf, (0, 0))
            draw_overlays(screen, weather)
        else:
            draw_status(screen, [
                "Syncing photos from Dropbox...",
                "This may take a moment on first run.",
                "",
                "Check the terminal for progress.",
            ])
            draw_overlays(screen, weather)

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
