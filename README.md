# Raspberry Pi Photo Slideshow — Setup Guide

## 1. Install Dependencies

```bash
sudo apt update
sudo apt install -y python3-pygame python3-pil libheif-dev
pip install pillow-heif --break-system-packages
```

`urllib` is built into Python 3 so no extra install is needed for networking or weather. `pillow-heif` enables automatic HEIC/HEIF conversion for iPhone photos — if you only upload JPGs you can skip that last line.

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

| Setting | Value | Description |
|---|---|---|
| `GDRIVE_API_KEY` | your key | Google Drive API key (see Section 4) |
| `GDRIVE_FOLDER_ID` | your folder ID | From your Google Drive share link |
| `IMAGE_FOLDER` | `~/slideshow_cache/` | Local cache folder on the Pi (auto-created) |
| `GDRIVE_SYNC_INTERVAL` | `300` | Seconds between Drive sync checks (5 min) |
| `SLIDE_DURATION` | `3` | Seconds per image |
| `TRANSITION` | `"crossfade"` | `"crossfade"` or `"cut"` |
| `IMAGE_ORDER` | `"random"` | `"random"` or `"sequential"` |
| `LATITUDE` | `33.749` | Your latitude (for weather) |
| `LONGITUDE` | `-84.388` | Your longitude (for weather) |
| `TEMP_UNIT` | `"F"` | `"F"` for Fahrenheit, `"C"` for Celsius |

### Finding Your Latitude & Longitude
1. Open **Google Maps** on your phone or computer
2. Long-press (or right-click) your location
3. The coordinates appear at the top of the info card, e.g. `33.749, -84.388`
4. Copy those values into the config block

### Finding Your Google Drive Folder ID
Your folder share link looks like:
```
https://drive.google.com/drive/folders/1eJzfxxxxxxxxxxxxxxxxxxxxxxx?usp=sharing
```
The folder ID is the long string between `/folders/` and `?` — in this example: `1eJzfxxxxxxxxxxxxxxxxxxxxxxx`

---

## 4. Set Up Google Drive (one-time, ~5 min)

Photos are managed entirely from your phone via Google Drive — no Dropbox, no daemon, nothing extra installed on the Pi.

### Step 1 — Create and share your photo folder
1. Open **Google Drive** on your phone or computer
2. Tap **"+ New"** → **"Folder"** → name it `Slideshow`
3. Add your photos to the folder
4. Right-click (or long-press) the folder → **"Share"** → **"Change to anyone with the link"** → set to **"Viewer"** → copy the link

### Step 2 — Get a free Google Drive API key
1. Go to **https://console.cloud.google.com** and sign in
2. Click **"Select a project"** → **"New Project"** → name it anything → **"Create"**
3. In the left menu go to **"APIs & Services"** → **"Library"**
4. Search for **"Google Drive API"** → click it → click **"Enable"**
5. Go to **"APIs & Services"** → **"Credentials"**
6. Click **"+ Create Credentials"** → **"API Key"**
7. Copy the key (looks like `AIzaSyB_xxxxxxxxxxxxxxxxxxxxxxx`)
8. Paste it into the `GDRIVE_API_KEY` config variable in `slideshow.py`

> No billing required. The free tier allows far more requests per day than this project will ever use.

### Step 3 — Managing photos going forward
To add or remove photos just open the **Google Drive** app on your phone, go to your Slideshow folder, and add/delete photos as normal. The Pi checks for changes every 5 minutes and updates the local cache automatically.

---

## 5. Run the Script

```bash
python3 ~/slideshow.py
```

On first launch you'll see **"Syncing photos from Google Drive..."** on screen while photos download. Once cached they display immediately on future runs. Expected terminal output:

```
[GDrive] Starting sync...
[GDrive] Found 6 image(s) in Drive folder.
[GDrive] Downloading: photo1.jpg
[GDrive] Saved: photo1.jpg (1842 KB)
[GDrive] Sync complete.
```

---

## 6. Autostart on Boot (systemd)

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

## 7. Touch Controls

| Touch Area | Action |
|---|---|
| Left 1/3 of screen | Previous photo |
| Right 1/3 of screen | Next photo |
| Middle 1/3 | No action |

Keyboard shortcuts also work: `←` / `→` to navigate, `Esc` to quit.

---

## 8. Troubleshooting

**"Syncing photos from Google Drive..." never goes away:**
- Check the terminal for error messages
- Confirm the folder is shared as "Anyone with the link" (Viewer)
- Confirm the Google Drive API is enabled in your Google Cloud project
- Confirm your API key is correct in the config

**`403 forbidden` error in terminal:**
The Drive API is not enabled for your API key. Go to console.cloud.google.com → APIs & Services → Library → search "Google Drive API" → Enable.

**`0 files found` in terminal:**
The folder sharing setting is wrong. Open Google Drive, right-click the Slideshow folder → Share → make sure it says "Anyone with the link" not "Restricted".

**Screen goes blank:**
The script calls `xset s off` and `xset s noblank` on startup. If blanking still occurs, add these lines to `/etc/xdg/lxsession/LXDE-pi/autostart`:
```
@xset s off
@xset -dpms
@xset s noblank
```

**Weather shows "unavailable":**
Check your latitude/longitude values and that the Pi has internet access. The script retries every 10 minutes automatically.

**Images not loading from cache:**
Supported formats are `.jpg`, `.jpeg`, `.png`, `.gif`, and `.webp`. HEIC/HEIF files from iPhones are automatically converted to JPG during sync as long as `pillow-heif` is installed. RAW files are not supported. If HEIC conversion is not working, run:
```bash
pip install pillow-heif --break-system-packages
```

**Font looks wrong:**
If `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` is missing, install it:
```bash
sudo apt install -y fonts-dejavu-core
```
