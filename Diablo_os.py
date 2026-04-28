# =========================
# DIABLO OS — CONFIG CENTRALE
# =========================

VERSION = "7.0.0"

from pathlib import Path

# Chemins
BASE_DIR    = Path.home()
MEMORY_FILE = BASE_DIR / "diablo_memory.json"
BACKUP_FILE = BASE_DIR / "diablo_memory.bak.json"
LOG_FILE    = BASE_DIR / "diablo.log"

# GitHub
UPDATE_URL = "https://raw.githubusercontent.com/diallo65377-lgtm/Diablo/main/diablo/main.py"

# Timings
UPDATE_INTERVAL  = 3600   # 1 heure
BRAIN_INTERVAL   = 30     # 30 secondes
DEBOUNCE_DELAY   = 300    # 5 minutes
MIN_PATTERN_COUNT = 3

# Batterie
LOW_BATTERY_THRESHOLD      = 15
CRITICAL_BATTERY_THRESHOLD = 5
BATTERY_AI_THRESHOLD       = 20
BATTERY_AI_INTERVAL        = 300  # 5 minutes

# Mode nuit / réveil
SLEEP_HOUR = 0   # 00h00
WAKE_HOUR  = 7   # 07h00

# Groq API
GROQ_MODEL       = "llama-3.1-8b-instant"
GROQ_API_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MAX_TOKENS  = 512
GROQ_HISTORY_MAX = 10

# Actions hardware reconnues par l'IA
NATURAL_ACTIONS = {
    "TORCH_ON", "TORCH_OFF",
    "WIFI_ON",  "WIFI_OFF",
    "VOL_MAX",  "VOL_MUTE",
    "VIBRATE",  "PHOTO",
    "SCREENSHOT", "RIEN",
}

# Applications Android connues
KNOWN_APPS = {
    "youtube":      "com.google.android.youtube",
    "whatsapp":     "com.whatsapp",
    "chrome":       "com.android.chrome",
    "maps":         "com.google.android.apps.maps",
    "photos":       "com.google.android.apps.photos",
    "galerie":      "com.gallery20",
    "facebook":     "com.facebook.katana",
    "snapchat":     "com.snapchat.android",
    "spotify":      "com.spotify.music",
    "tiktok":       "com.zhiliaoapp.musically.go",
    "discord":      "com.discord",
    "parametres":   "com.android.settings",
    "paramètres":   "com.android.settings",
    "telephone":    "com.android.phone",
    "téléphone":    "com.android.phone",
    "claude":       "com.anthropic.claude",
    "meteo":        "com.rlk.weathers",
    "météo":        "com.rlk.weathers",
    "xender":       "cn.xender",
    "xbrowser":     "com.xbrowser.play",
    "zarchiver":    "ru.zdevs.zarchiver",
    "termux":       "com.termux",
    "contacts":     "com.sh.smart.caller",
    "magicshow":    "com.transsion.magicshow",
    "netflix":      "com.netflix.mediaclient",
    "gmail":        "com.google.android.gm",
    "drive":        "com.google.android.apps.docs",
    "play":         "com.android.vending",
}

# Médiathèque
SOURCE_DIRS = [
    "/storage/emulated/0/Download",
    "/storage/emulated/0/Xender/video",
]
MEDIA_BASE  = "/storage/emulated/0/Movies/Ma_Mangatheque"
SERIES_DIR  = f"{MEDIA_BASE}/Mes_Series"
FILMS_DIR   = f"{MEDIA_BASE}/_Films"
ANIMES_DIR  = f"{MEDIA_BASE}/Animes"
MANGAS_DIR  = f"{MEDIA_BASE}/Mangas"
VIDEO_EXT   = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv")

ANIME_KEYWORDS = [
    "anime", "animé", "vostfr", "vf", "crunchyroll",
    "one piece", "naruto", "bleach", "dragon ball",
    "attack on titan", "demon slayer", "jujutsu",
    "my hero", "sword art", "hunter x hunter",
    "fullmetal", "death note", "tokyo ghoul",
]
