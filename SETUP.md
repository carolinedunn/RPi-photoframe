# Raspberry Pi Photo Slideshow — Setup Guide

## 1. Install Dependencies

```bash
sudo apt update
sudo apt install -y python3-pygame
```

No other Python packages are needed — `urllib` is built into Python 3.

---

## 2. Copy the Script

Place `slideshow.py` in your home directory:

```bash
cp slideshow.py ~/slideshow.py
chmod +x ~/slideshow.py
```

---

## 3. Configure the Script

Open `slideshow.py` and edit the **USER CONFIGURATION** block at the top:

| Setting | Default | Description |
|---|---|---|
| `IMAGE_FOLDER` | `~/Dropbox/Slideshow/` | Path to your photos |
| `SLIDE_DURATION` | `30` | Seconds per image |
| `TRANSITION` | `"crossfade"` | `"crossfade"` or `"cut"` |
| `IMAGE_ORDER` | `"random"` | `"random"` or `"sequential"` |
| `LATITUDE` | `33.749` | Your latitude |
| `LONGITUDE` | `-84.388` | Your longitude |
| `TEMP_UNIT` | `"F"` | `"F"` or `"C"` |

### Finding Your Latitude & Longitude
1. Open **Google Maps** on your phone or computer
2. Long-press (or right-click) your location
3. The coordinates appear at the top of the info card, e.g. `33.749, -84.388`
4. Copy those values into the config block

---

## 4. Install the systemd Service

```bash
# Copy the service file
sudo cp slideshow@.service /etc/systemd/system/

# Enable and start it (replace 'pi' with your actual username)
sudo systemctl daemon-reload
sudo systemctl enable slideshow@pi.service
sudo systemctl start slideshow@pi.service

# Check status
sudo systemctl status slideshow@pi.service
```

To stop or disable:
```bash
sudo systemctl stop slideshow@pi.service
sudo systemctl disable slideshow@pi.service
```

---

## 5. Install Dropbox (Headless) on Raspberry Pi OS

Dropbox lets you manage photos from your phone and they automatically appear on the Pi.

### Step 1 — Download the Dropbox daemon
```bash
cd ~ && wget -O - "https://www.dropbox.com/download?plat=lnx.armv7hf" | tar xzf -
```
> For 64-bit Pi OS use `lnx.aarch64` instead of `lnx.armv7hf`

### Step 2 — Start Dropbox and link your account
```bash
~/.dropbox-dist/dropboxd &
```
Dropbox will print a URL like:
```
Please visit https://www.dropbox.com/cli_link_nonce?nonce=XXXX to link this device.
```
Open that URL on your phone or computer and sign in — the Pi will link automatically.

### Step 3 — Install the Dropbox CLI (optional but recommended)
```bash
sudo wget -O /usr/local/bin/dropbox \
  "https://www.dropbox.com/download?dl=packages/dropbox.py"
sudo chmod +x /usr/local/bin/dropbox
dropbox status
```

### Step 4 — Auto-start Dropbox on boot
```bash
# Add to crontab
crontab -e
```
Add this line:
```
@reboot /bin/bash -c "~/.dropbox-dist/dropboxd &"
```

### Step 5 — Create the Slideshow folder
In the Dropbox app on your phone, create a folder called **Slideshow** and add your photos there. They'll sync to `~/Dropbox/Slideshow/` on the Pi automatically.

---

## 6. Touch Controls

| Touch Area | Action |
|---|---|
| Left 1/3 of screen | Previous photo |
| Right 1/3 of screen | Next photo |
| Middle 1/3 | No action |

Keyboard shortcuts also work: `←` / `→` to navigate, `Esc` to quit.

---

## 7. Troubleshooting

**Screen goes blank:** Make sure the script is running — it calls `xset s off` and `xset -dpms` on startup. You can also add these to `/etc/xdg/lxsession/LXDE-pi/autostart`:
```
@xset s off
@xset -dpms
@xset s noblank
```

**Weather shows "unavailable":** Check your latitude/longitude values and that the Pi has internet access. The script retries every 10 minutes automatically.

**Images not loading:** Confirm the folder path in the config and that photos are in `.jpg`, `.jpeg`, `.png`, or `.gif` format.

**Font looks wrong:** If `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` is missing, install it:
```bash
sudo apt install -y fonts-dejavu-core
```
