#!/usr/bin/env python3
"""
Raspberry Pi Photo Slideshow
Syncs photos from a public Google Drive folder using the Drive API.
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

# Google Drive API key (from console.cloud.google.com)
GDRIVE_API_KEY        = "AIzaSyB_xxxxxxxxxxxxxxxxxxxxxxx"

# Google Drive folder ID (the long string from your share link)
GDRIVE_FOLDER_ID      = "1eJzxxxxxxxxxxxxxxxxxxxxxxx"

# Local folder where synced photos are cached on the Pi
IMAGE_FOLDER          = os.path.expanduser("~/slideshow_cache/")

# How often to check Google Drive for new/removed photos (seconds)
GDRIVE_SYNC_INTERVAL  = 300   # 5 minutes

SLIDE_DURATION        = 3           # seconds per image
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
OVERLAY_COLOR         = (50, 50, 50, 128)
FONT_PATH             = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ============================================================
#  END OF USER CONFIGURATION
# ============================================================

import pygame

SUPPORTED_MIMETYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/heic", "image/heif",
}
SUPPORTED_EXTS     = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
HEIC_EXTS          = {".heic", ".heif"}
ALL_DOWNLOAD_EXTS  = SUPPORTED_EXTS | HEIC_EXTS

# Try to import pillow-heif for HEIC conversion
try:
    from pillow_heif import register_heif_opener
    from PIL import Image
    register_heif_opener()
    HEIC_SUPPORT = True
    print("[HEIC] pillow-heif loaded — HEIC/HEIF images will be auto-converted to JPG.")
except ImportError:
    HEIC_SUPPORT = False
    print("[HEIC] pillow-heif not installed — HEIC files will be skipped.")
    print("[HEIC] To enable: pip install pillow-heif --break-system-packages")


# ---------------------------------------------------------------
#  Google Drive sync using API key
# ---------------------------------------------------------------

def fetch_gdrive_file_list(folder_id, api_key):
    """
    Use the Drive API v3 files.list to get all image files in a public folder.
    Returns list of (file_id, name) tuples, or None on error.
    """
    params = urllib.parse.urlencode({
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "files(id,name,mimeType)",
        "key": api_key,
        "pageSize": 1000,
    })
    url = f"https://www.googleapis.com/drive/v3/files?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        files = [
            (f["id"], f["name"])
            for f in data.get("files", [])
            if f.get("mimeType") in SUPPORTED_MIMETYPES
            or os.path.splitext(f.get("name", ""))[1].lower() in ALL_DOWNLOAD_EXTS
        ]
        return files
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[GDrive] files.list HTTP {e.code}: {body}")
    except Exception as e:
        print(f"[GDrive] files.list error: {e}")
    return None


def download_gdrive_file(file_id, api_key, local_path):
    """Download a file from Google Drive using the API key."""
    url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?alt=media&key={api_key}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
        with open(local_path, "wb") as f:
            f.write(content)
        print(f"[GDrive] Saved: {os.path.basename(local_path)} ({len(content)//1024} KB)")
        return True
    except urllib.error.HTTPError as e:
        print(f"[GDrive] Download HTTP {e.code} for {file_id}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[GDrive] Download error for {file_id}: {e}")
    return False


def convert_heic_to_jpg(heic_path):
    """
    Convert a HEIC/HEIF file to JPG. Returns the new JPG path on success,
    or None if conversion fails or pillow-heif is not installed.
    """
    if not HEIC_SUPPORT:
        return None
    jpg_path = os.path.splitext(heic_path)[0] + ".jpg"
    try:
        img = Image.open(heic_path)
        img = img.convert("RGB")
        img.save(jpg_path, "JPEG", quality=92)
        os.remove(heic_path)
        print(f"[HEIC] Converted: {os.path.basename(heic_path)} -> {os.path.basename(jpg_path)}")
        return jpg_path
    except Exception as e:
        print(f"[HEIC] Conversion failed for {heic_path}: {e}")
        return None


def sync_gdrive_folder(folder_id, api_key, local_folder):
    """
    List the Drive folder, download new images, convert HEIC to JPG,
    and remove local files deleted from Drive.
    Returns True on success, False on failure.
    """
    os.makedirs(local_folder, exist_ok=True)

    entries = fetch_gdrive_file_list(folder_id, api_key)
    if entries is None:
        return False

    if not entries:
        print("[GDrive] No image files found in folder (check folder is shared as 'Anyone with link').")
        return False

    print(f"[GDrive] Found {len(entries)} image(s) in Drive folder.")

    remote = {name: fid for fid, name in entries}

    # Build a set of all expected local names (HEIC files become .jpg after conversion)
    expected_local = set()
    for name in remote:
        ext = os.path.splitext(name)[1].lower()
        if ext in HEIC_EXTS:
            expected_local.add(os.path.splitext(name)[0] + ".jpg")
        else:
            expected_local.add(name)

    # Download new files
    for name, fid in remote.items():
        ext = os.path.splitext(name)[1].lower()
        is_heic = ext in HEIC_EXTS
        # For HEIC files, check if the converted JPG already exists
        local_name = (os.path.splitext(name)[0] + ".jpg") if is_heic else name
        local_path = os.path.join(local_folder, local_name)

        if not os.path.exists(local_path):
            raw_path = os.path.join(local_folder, name)
            print(f"[GDrive] Downloading: {name}")
            if download_gdrive_file(fid, api_key, raw_path):
                if is_heic:
                    convert_heic_to_jpg(raw_path)

    # Remove local files deleted from Drive
    for fname in os.listdir(local_folder):
        if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTS:
            if fname not in expected_local:
                print(f"[GDrive] Removing {fname} (deleted from Drive)")
                try:
                    os.remove(os.path.join(local_folder, fname))
                except Exception:
                    pass

    return True


class GDriveSyncThread(threading.Thread):
    def __init__(self, folder_id, api_key, local_folder, interval):
        super().__init__(daemon=True)
        self.folder_id    = folder_id
        self.api_key      = api_key
        self.local_folder = local_folder
        self.interval     = interval
        self.synced_ok    = False

    def run(self):
        while True:
            print("[GDrive] Starting sync...")
            self.synced_ok = sync_gdrive_folder(
                self.folder_id, self.api_key, self.local_folder
            )
            print(f"[GDrive] Sync {'complete' if self.synced_ok else 'FAILED (will retry)'}.")
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
        [f"{now.strftime('%a, %b %-d')}  ·  {now.strftime('%-I:%M %p')}"],
        m, sh - m, anchor="bottomleft"
    )
    draw_overlay_box(
        screen,
        ["Weather unavailable"] if weather is None else [weather["line1"], weather["line2"]],
        sw - m, m, anchor="topright"
    )


# ---------------------------------------------------------------
#  Status screen
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

    weather_thread = WeatherThread()
    weather_thread.start()

    sync_thread = GDriveSyncThread(
        GDRIVE_FOLDER_ID, GDRIVE_API_KEY, IMAGE_FOLDER, GDRIVE_SYNC_INTERVAL
    )
    sync_thread.start()

    image_list   = []
    index        = 0
    current_surf = None
    slide_start  = time.time()

    running = True
    while running:
        now     = time.time()
        weather = weather_thread.get()

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

        # First load after sync completes
        if current_surf is None and fresh_list:
            image_list = fresh_list
            if IMAGE_ORDER == "random":
                random.shuffle(image_list)
            current_surf = load_and_scale(image_list[0], SW, SH)
            index = 0
            slide_start = time.time()

        # Advance slide
        if now - slide_start >= SLIDE_DURATION and current_surf is not None:
            image_list = fresh_list
            if IMAGE_ORDER == "random":
                random.shuffle(image_list)
            if image_list:
                index = (index + 1) % len(image_list)
                old_surf = current_surf
                new_surf = load_and_scale(image_list[index], SW, SH)
                if new_surf and old_surf and TRANSITION == "crossfade":
                    crossfade(screen, old_surf, new_surf,
                              overlay_fn=lambda s: draw_overlays(s, weather))
                current_surf = new_surf or old_surf
            slide_start = time.time()

        # Draw
        if current_surf:
            screen.blit(current_surf, (0, 0))
            draw_overlays(screen, weather)
        else:
            draw_status(screen, [
                "Syncing photos from Google Drive...",
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
