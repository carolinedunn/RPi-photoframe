#!/usr/bin/env python3
"""
Raspberry Pi Photo Slideshow
A fullscreen photo slideshow with date/time and weather overlays.
"""

import os
import sys
import random
import threading
import time
import datetime
import urllib.request
import urllib.error
import json
import subprocess

# ============================================================
#  USER CONFIGURATION — edit these settings to your liking
# ============================================================

IMAGE_FOLDER      = os.path.expanduser("~/Dropbox/Slideshow/")
SLIDE_DURATION    = 30          # seconds per image
TRANSITION        = "crossfade" # "crossfade" or "cut"
IMAGE_ORDER       = "random"    # "random" or "sequential"

LATITUDE          = 33.749      # Your latitude  (e.g. Atlanta, GA)
LONGITUDE         = -84.388     # Your longitude (e.g. Atlanta, GA)
TEMP_UNIT         = "F"         # "F" for Fahrenheit, "C" for Celsius

WEATHER_REFRESH   = 600         # seconds between weather fetches (10 min)
CROSSFADE_STEPS   = 30          # number of frames in crossfade transition
OVERLAY_FONT_SIZE = 22          # font size for overlays
OVERLAY_PADDING   = 8           # internal padding inside overlay boxes (px)
OVERLAY_MARGIN    = 10          # margin from screen edges (px)
OVERLAY_COLOR     = (50, 50, 50, 128)   # RGBA: dark gray 50% opacity
TEXT_COLOR        = (255, 255, 255, 255)  # RGBA: white

FONT_PATH         = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ============================================================
#  END OF USER CONFIGURATION
# ============================================================

import pygame

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif"}

# --------------- Weather helpers ---------------

WMO_CODES = {
    0:  "Clear",
    1:  "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Heavy Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Heavy Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
    77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm",
    96: "Thunderstorm w/ Hail", 99: "Thunderstorm w/ Hail",
}

def wmo_label(code):
    return WMO_CODES.get(code, "Unknown")

def fetch_weather():
    """Fetch current weather from Open-Meteo. Returns a dict or None on failure."""
    unit_param = "fahrenheit" if TEMP_UNIT.upper() == "F" else "celsius"
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current_weather=true"
        f"&temperature_unit={unit_param}"
        f"&wind_speed_unit=mph"
        f"&timezone=auto"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        cw = data["current_weather"]
        temp = cw["temperature"]
        wind = cw["windspeed"]
        code = int(cw["weathercode"])
        label = wmo_label(code)
        unit_sym = "°F" if TEMP_UNIT.upper() == "F" else "°C"
        return {
            "line1": f"{temp:.0f}{unit_sym}  {label}",
            "line2": f"Wind: {wind:.0f} mph",
        }
    except Exception:
        return None


class WeatherThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.data = None
        self.lock = threading.Lock()
        self._stop = False

    def run(self):
        while not self._stop:
            result = fetch_weather()
            with self.lock:
                self.data = result
            for _ in range(WEATHER_REFRESH):
                if self._stop:
                    return
                time.sleep(1)

    def get(self):
        with self.lock:
            return self.data


# --------------- Image helpers ---------------

def load_image_list(folder):
    if not os.path.isdir(folder):
        return []
    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    ]
    return sorted(files)


def scale_image(surface, target_w, target_h):
    """Scale surface to fit target dimensions preserving aspect ratio (letterbox)."""
    iw, ih = surface.get_size()
    scale = min(target_w / iw, target_h / ih)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    scaled = pygame.transform.smoothscale(surface, (new_w, new_h))
    result = pygame.Surface((target_w, target_h))
    result.fill((0, 0, 0))
    result.blit(scaled, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return result


def load_and_scale(path, w, h):
    try:
        img = pygame.image.load(path).convert()
        return scale_image(img, w, h)
    except Exception:
        return None


# --------------- Overlay drawing ---------------

def get_font(size=OVERLAY_FONT_SIZE):
    if os.path.exists(FONT_PATH):
        return pygame.font.Font(FONT_PATH, size)
    return pygame.font.SysFont("sans", size)


def draw_overlay_box(screen, lines, x, y, anchor="topleft"):
    """
    Draws a semi-transparent rounded box with text lines.
    anchor: 'topleft', 'bottomleft', 'topright', 'bottomright'
    x, y are the corner position based on anchor.
    """
    font = get_font()
    pad = OVERLAY_PADDING

    rendered = [font.render(line, True, (255, 255, 255)) for line in lines]
    text_w = max(r.get_width() for r in rendered)
    line_h = rendered[0].get_height()
    text_h = line_h * len(rendered) + (len(rendered) - 1) * 4

    box_w = text_w + pad * 2
    box_h = text_h + pad * 2

    # Resolve anchor to top-left corner of box
    if anchor == "topleft":
        bx, by = x, y
    elif anchor == "bottomleft":
        bx, by = x, y - box_h
    elif anchor == "topright":
        bx, by = x - box_w, y
    elif anchor == "bottomright":
        bx, by = x - box_w, y - box_h
    else:
        bx, by = x, y

    # Draw box
    box_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    box_surf.fill((0, 0, 0, 0))
    pygame.draw.rect(box_surf, OVERLAY_COLOR, (0, 0, box_w, box_h), border_radius=8)
    screen.blit(box_surf, (bx, by))

    # Draw text lines
    ty = by + pad
    for r in rendered:
        screen.blit(r, (bx + pad, ty))
        ty += line_h + 4


def draw_overlays(screen, weather):
    sw, sh = screen.get_size()
    margin = OVERLAY_MARGIN

    # Date/time — bottom-left
    now = datetime.datetime.now()
    date_str = now.strftime("%A, %B %-d")
    time_str = now.strftime("%-I:%M %p")
    draw_overlay_box(
        screen,
        [f"{date_str}  ·  {time_str}"],
        margin, sh - margin,
        anchor="bottomleft"
    )

    # Weather — top-right
    if weather is None:
        weather_lines = ["Weather unavailable"]
    else:
        weather_lines = [weather["line1"], weather["line2"]]
    draw_overlay_box(
        screen,
        weather_lines,
        sw - margin, margin,
        anchor="topright"
    )


# --------------- No-photos screen ---------------

def draw_no_photos(screen):
    screen.fill((0, 0, 0))
    font = get_font(28)
    text = font.render("No photos found", True, (255, 255, 255))
    rect = text.get_rect(center=(screen.get_width() // 2, screen.get_height() // 2))
    screen.blit(text, rect)


# --------------- Crossfade transition ---------------

def crossfade(screen, old_surf, new_surf, steps=CROSSFADE_STEPS, weather_fn=None):
    clock = pygame.time.Clock()
    for i in range(1, steps + 1):
        alpha = int(255 * i / steps)
        screen.blit(old_surf, (0, 0))
        new_surf.set_alpha(alpha)
        screen.blit(new_surf, (0, 0))
        new_surf.set_alpha(255)
        if weather_fn:
            weather_fn(screen)
        pygame.display.flip()
        clock.tick(30)


# --------------- Main loop ---------------

def main():
    # Disable screen blanking
    try:
        subprocess.Popen(["xset", "s", "off"])
        subprocess.Popen(["xset", "-dpms"])
    except Exception:
        pass

    pygame.init()
    pygame.mouse.set_visible(False)

    info = pygame.display.Info()
    SW, SH = info.current_w, info.current_h
    screen = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN)
    pygame.display.set_caption("Slideshow")

    clock = pygame.time.Clock()

    # Start weather thread
    weather_thread = WeatherThread()
    weather_thread.start()

    image_list = load_image_list(IMAGE_FOLDER)
    index = 0
    if IMAGE_ORDER == "random" and image_list:
        random.shuffle(image_list)

    current_surf = None
    slide_start = time.time()

    def load_next_image(idx, img_list):
        if not img_list:
            return None, idx
        path = img_list[idx % len(img_list)]
        surf = load_and_scale(path, SW, SH)
        return surf, idx

    # Load first image
    if image_list:
        current_surf, _ = load_next_image(index, image_list)

    running = True
    while running:
        now = time.time()
        weather = weather_thread.get()

        # --- Event handling ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_RIGHT:
                    slide_start = now - SLIDE_DURATION  # force advance
                elif event.key == pygame.K_LEFT:
                    index = max(0, index - 2)
                    slide_start = now - SLIDE_DURATION
            elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
                if event.type == pygame.FINGERUP:
                    tx = event.x * SW
                else:
                    tx = event.pos[0]
                if tx < SW / 3:
                    # Previous
                    index = max(0, index - 2)
                    slide_start = now - SLIDE_DURATION
                elif tx > 2 * SW / 3:
                    # Next — force advance
                    slide_start = now - SLIDE_DURATION

        # --- Slide advance ---
        if now - slide_start >= SLIDE_DURATION:
            image_list = load_image_list(IMAGE_FOLDER)
            if IMAGE_ORDER == "random" and image_list:
                random.shuffle(image_list)

            index = (index + 1) % max(len(image_list), 1)
            old_surf = current_surf

            if image_list:
                new_surf = load_and_scale(image_list[index % len(image_list)], SW, SH)
            else:
                new_surf = None

            if new_surf and old_surf and TRANSITION == "crossfade":
                crossfade(screen, old_surf, new_surf, weather_fn=lambda s: draw_overlays(s, weather))
            current_surf = new_surf
            slide_start = time.time()

        # --- Draw ---
        if current_surf:
            screen.blit(current_surf, (0, 0))
        else:
            draw_no_photos(screen)

        draw_overlays(screen, weather)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
