import os
import sys
import json
import time
import shutil
import re
import logging
import threading
import subprocess
import hashlib
import signal
from datetime import datetime
from pathlib import Path

# Import optionnel de requests
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# =========================
# CONFIG
# =========================
VERSION = "6.0.0"
BASE_DIR = Path.home()
MEMORY_FILE = BASE_DIR / "diablo_memory.json"
BACKUP_FILE = BASE_DIR / "diablo_memory.bak.json"
LOG_FILE = BASE_DIR / "diablo.log"
UPDATE_URL = "https://raw.githubusercontent.com/diallo65377-lgtm/Diablo/main/Diablo_os.py"
UPDATE_INTERVAL = 3600
BRAIN_INTERVAL = 30
DEBOUNCE_DELAY = 300
MIN_PATTERN_COUNT = 3
LOW_BATTERY_THRESHOLD = 15
CRITICAL_BATTERY_THRESHOLD = 5

# Groq API
GROQ_MODEL      = "llama-3.1-8b-instant"
GROQ_API_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MAX_TOKENS = 512
GROQ_HISTORY_MAX = 10

# IA Batterie
BATTERY_AI_THRESHOLD = 20
BATTERY_AI_INTERVAL  = 300

# Mode nuit / réveil
SLEEP_HOUR = 0    # 00h00
WAKE_HOUR  = 7    # 07h00

# Actions reconnues par langage naturel
NATURAL_ACTIONS = {
    "TORCH_ON", "TORCH_OFF",
    "WIFI_ON",  "WIFI_OFF",
    "VOL_MAX",  "VOL_MUTE",
    "VIBRATE",  "PHOTO",
    "SCREENSHOT", "RIEN",
}

# Apps connues
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

# =========================
# COULEURS TERMINAL
# =========================
class C:
    RESET  = "\033[0m"
    VERT   = "\033[92m"
    ROUGE  = "\033[91m"
    JAUNE  = "\033[93m"
    CYAN   = "\033[96m"
    BLEU   = "\033[94m"
    GRAS   = "\033[1m"
    VIOLET = "\033[95m"

def color(t, c): return c + t + C.RESET


# =========================
# LOGGING
# =========================
def setup_logging():
    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S"
    )
    logger = logging.getLogger("diablo")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 500_000:
            LOG_FILE.rename(LOG_FILE.with_suffix(".bak.log"))
        fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARN] Log fichier désactivé : {e}", flush=True)

    return logger

logger   = setup_logging()
log      = logger.info
log_warn = logger.warning
log_err  = logger.error
log_dbg  = logger.debug


# =========================
# MODE NUIT / RÉVEIL
# =========================
class SleepWakeManager:
    """
    Gère le mode nuit (00h) et le réveil (7h) automatiquement.
    Surveille l'heure en arrière-plan et déclenche les actions.
    """

    def __init__(self, api):
        self.api         = api
        self._stop       = threading.Event()
        self._mode_nuit  = False  # True = mode nuit actif
        self._last_check = {"sleep": None, "wake": None}

    def stop(self):
        self._stop.set()

    def _is_sleep_time(self):
        h = datetime.now().hour
        if SLEEP_HOUR <= WAKE_HOUR:
            return SLEEP_HOUR <= h < WAKE_HOUR
        else:
            return h >= SLEEP_HOUR or h < WAKE_HOUR

    def _activer_mode_nuit(self):
        if self._mode_nuit:
            return
        self._mode_nuit = True
        log("🌙 Mode nuit activé")

        self.api.execute("VOL_MUTE")
        self.api.execute("WIFI_OFF")
        self.api.execute("NOTIFY",
            "🌙 Bonne nuit Aladji — Mode nuit activé.\n"
            "Wi-Fi coupé, volume silencieux."
        )
        print(color("\n🌙 MODE NUIT ACTIVÉ — Bonne nuit Aladji !\n", C.VIOLET))

    def _activer_mode_reveil(self):
        if not self._mode_nuit:
            return
        self._mode_nuit = False
        log("☀️ Mode réveil activé")

        self.api.execute("WIFI_ON")
        self.api.execute("VOL_MAX")
        self.api.execute("VIBRATE")
        self.api.execute("NOTIFY",
            f"☀️ Bonjour Aladji ! Il est {datetime.now().strftime('%H:%M')}.\n"
            "Wi-Fi activé, volume remis. Bonne journée !"
        )
        print(color("\n☀️ BONJOUR ALADJI ! Mode réveil activé.\n", C.JAUNE))

    def _tick(self):
        heure = datetime.now().hour
        date  = datetime.now().date()

        # Vérifier mode nuit (00h)
        if heure == SLEEP_HOUR and self._last_check["sleep"] != date:
            self._last_check["sleep"] = date
            self._activer_mode_nuit()

        # Vérifier réveil (7h)
        elif heure == WAKE_HOUR and self._last_check["wake"] != date:
            self._last_check["wake"] = date
            self._activer_mode_reveil()

    def run(self):
        log("Mode nuit/réveil démarré")

        # Vérifier au démarrage si on est déjà en mode nuit
        if self._is_sleep_time():
            self._mode_nuit = True
            log("🌙 Démarrage en mode nuit")

        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log_err(f"SleepWake error : {e}")
            self._stop.wait(timeout=60)  # Vérifier toutes les minutes

    def status(self):
        heure = datetime.now().strftime("%H:%M")
        if self._mode_nuit:
            return color(f"🌙 Mode NUIT actif ({heure})", C.VIOLET)
        else:
            return color(f"☀️  Mode JOUR actif ({heure})", C.JAUNE)

    def forcer_nuit(self):
        self._mode_nuit = False  # reset pour forcer
        self._activer_mode_nuit()

    def forcer_reveil(self):
        self._mode_nuit = True  # reset pour forcer
        self._activer_mode_reveil()


# =========================
# MÉDIATHÈQUE
# =========================
class MediaOrganizer:

    def __init__(self, api=None):
        self.api = api

    def _stats_vides(self):
        return {"scan": 0, "move": 0, "replace": 0, "skip": 0, "error": 0}

    def _is_anime(self, nom):
        n = nom.lower()
        for kw in ANIME_KEYWORDS:
            if kw in n:
                return True
        return False

    def _detect_type(self, nom):
        n = nom.lower()
        if self._is_anime(n):
            return "anime"
        serie_patterns = [
            r"s\d{1,2}e\d{1,3}", r"\d{1,2}x\d{1,3}",
            r"episode\s*\d+", r"saison\s*\d+", r"ep\s*\d+",
        ]
        for p in serie_patterns:
            if re.search(p, n):
                return "serie"
        if re.search(r"(19|20)\d{2}", n):
            return "film"
        if re.search(r"1080|720|bluray|webrip|x264|x265|brrip|hdtv", n):
            return "film"
        return None

    def _nettoyer(self, nom):
        nom = re.sub(
            r"\b(1080p|720p|480p|bluray|brrip|webrip|x264|x265|"
            r"vf|vostfr|aac|hevc|hdtv|proper|repack)\b",
            "", nom, flags=re.I
        )
        nom = re.sub(r"[._\-]+", " ", nom)
        nom = re.sub(r"\s+", " ", nom)
        return nom.strip().title()

    def _extraire_episode(self, nom):
        patterns = [
            r"s(\d{1,2})e(\d{1,3})", r"(\d{1,2})x(\d{1,3})",
            r"saison\s*(\d+).*?episode\s*(\d+)",
            r"ep\s*(\d+)", r"episode\s*(\d+)",
        ]
        for p in patterns:
            m = re.search(p, nom.lower())
            if m:
                if len(m.groups()) == 2:
                    return m.group(1).zfill(2), m.group(2).zfill(2)
                return "01", m.group(1).zfill(2)
        return None, None

    def _nom_serie(self, nom):
        nom = re.split(r"s\d|episode|ep\s*\d", nom, flags=re.I)[0]
        return self._nettoyer(nom)

    def _move_safe(self, src, dst, stats):
        try:
            if not os.path.exists(dst):
                shutil.move(src, dst)
                stats["move"] += 1
                return color("✔ déplacé", C.VERT)
            if os.path.getsize(src) > os.path.getsize(dst):
                os.remove(dst)
                shutil.move(src, dst)
                stats["replace"] += 1
                return color("♻ remplacé", C.JAUNE)
            os.remove(src)
            stats["skip"] += 1
            return color("✖ ignoré (doublon)", C.ROUGE)
        except Exception as e:
            stats["error"] += 1
            log_err(f"Move error : {e}")
            return color("⚠ erreur", C.ROUGE)

    def _afficher_resume(self, stats, titre):
        print(color(f"\n{'='*40}", C.BLEU))
        print(color(f"  RÉSULTAT — {titre}", C.BLEU))
        print(color(f"{'='*40}", C.BLEU))
        print(f"  Scanné    : {stats['scan']}")
        print(color(f"  Déplacé   : {stats['move']}", C.VERT))
        print(color(f"  Remplacé  : {stats['replace']}", C.JAUNE))
        print(color(f"  Ignoré    : {stats['skip']}", C.ROUGE))
        print(color(f"  Erreurs   : {stats['error']}", C.ROUGE))
        print()
        if self.api:
            total = stats["move"] + stats["replace"]
            if total > 0:
                self.api.execute("NOTIFY", f"📁 {titre} : {total} fichier(s) organisé(s)")

    def organiser_series(self):
        os.makedirs(SERIES_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n📺 Scan des séries…\n", C.CYAN))
        for source in SOURCE_DIRS:
            if not os.path.exists(source):
                continue
            for f in os.listdir(source):
                if not f.lower().endswith(VIDEO_EXT):
                    continue
                stats["scan"] += 1
                if self._detect_type(f) != "serie":
                    continue
                saison, ep = self._extraire_episode(f)
                if not ep:
                    continue
                serie = self._nom_serie(f)
                dest  = os.path.join(SERIES_DIR, serie, f"Saison {saison}")
                os.makedirs(dest, exist_ok=True)
                ext = os.path.splitext(f)[1]
                new = f"{serie} S{saison}E{ep}{ext}"
                res = self._move_safe(os.path.join(source, f), os.path.join(dest, new), stats)
                print(f"  {res}  →  {new}")
        self._afficher_resume(stats, "Séries")
        return stats

    def organiser_films(self):
        os.makedirs(FILMS_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n🎬 Scan des films…\n", C.CYAN))
        for source in SOURCE_DIRS:
            if not os.path.exists(source):
                continue
            for f in os.listdir(source):
                if not f.lower().endswith(VIDEO_EXT):
                    continue
                stats["scan"] += 1
                if self._detect_type(f) != "film":
                    continue
                film = self._nettoyer(os.path.splitext(f)[0])
                ext  = os.path.splitext(f)[1]
                res  = self._move_safe(os.path.join(source, f), os.path.join(FILMS_DIR, film + ext), stats)
                print(f"  {res}  →  {film}{ext}")
        self._afficher_resume(stats, "Films")
        return stats

    def organiser_animes(self):
        os.makedirs(ANIMES_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n🎌 Scan des animés…\n", C.VIOLET))
        for source in SOURCE_DIRS:
            if not os.path.exists(source):
                continue
            for f in os.listdir(source):
                if not f.lower().endswith(VIDEO_EXT):
                    continue
                stats["scan"] += 1
                if not self._is_anime(f.lower()):
                    continue
                saison, ep = self._extraire_episode(f)
                anime = self._nom_serie(f)
                if ep:
                    saison = saison or "01"
                    dest = os.path.join(ANIMES_DIR, anime, f"Saison {saison}")
                    os.makedirs(dest, exist_ok=True)
                    ext = os.path.splitext(f)[1]
                    new = f"{anime} S{saison}E{ep}{ext}"
                    res = self._move_safe(os.path.join(source, f), os.path.join(dest, new), stats)
                else:
                    dest = os.path.join(ANIMES_DIR, anime)
                    os.makedirs(dest, exist_ok=True)
                    new = f
                    res = self._move_safe(os.path.join(source, f), os.path.join(dest, f), stats)
                print(f"  {res}  →  {new}")
        self._afficher_resume(stats, "Animés")
        return stats

    def organiser_tout(self):
        print(color("\n🚀 Organisation complète…\n", C.GRAS))
        s1 = self.organiser_animes()
        s2 = self.organiser_series()
        s3 = self.organiser_films()
        total = sum([
            s1["move"] + s1["replace"],
            s2["move"] + s2["replace"],
            s3["move"] + s3["replace"],
        ])
        print(color(f"✅ Terminé ! {total} fichier(s) organisé(s).\n", C.VERT))
        if self.api:
            self.api.execute("NOTIFY", f"✅ Médiathèque : {total} fichier(s) organisé(s) !")

    def scanner(self):
        print(color("\n🔍 Scan en mode aperçu (aucun fichier déplacé)…\n", C.CYAN))
        trouve = {"series": [], "films": [], "animes": [], "inconnus": []}
        for source in SOURCE_DIRS:
            if not os.path.exists(source):
                print(color(f"  ⚠ Dossier introuvable : {source}", C.JAUNE))
                continue
            print(color(f"  📂 Source : {source}", C.BLEU))
            for f in os.listdir(source):
                if not f.lower().endswith(VIDEO_EXT):
                    continue
                t = self._detect_type(f)
                if t == "anime":   trouve["animes"].append(f)
                elif t == "serie": trouve["series"].append(f)
                elif t == "film":  trouve["films"].append(f)
                else:              trouve["inconnus"].append(f)
        for cat, files in trouve.items():
            if files:
                emoji = {"series": "📺", "films": "🎬", "animes": "🎌", "inconnus": "❓"}[cat]
                print(color(f"\n{emoji} {cat.upper()} ({len(files)})", C.BLEU))
                for f in files:
                    print(f"   • {f}")
        total = sum(len(v) for v in trouve.values())
        print(color(f"\nTotal : {total} vidéo(s) trouvée(s)\n", C.CYAN))

    def chercher(self, query):
        query = query.lower().strip()
        print(color(f"\n🔍 Recherche : '{query}'\n", C.CYAN))
        resultats = []
        for dossier, nom in [(SERIES_DIR, "Séries"), (FILMS_DIR, "Films"),
                              (ANIMES_DIR, "Animés"), (MANGAS_DIR, "Mangas")]:
            if not os.path.exists(dossier):
                continue
            for root, dirs, files in os.walk(dossier):
                for f in files:
                    if not f.lower().endswith(VIDEO_EXT):
                        continue
                    if query in f.lower() or query in root.lower():
                        rel = os.path.relpath(os.path.join(root, f), MEDIA_BASE)
                        resultats.append((nom, rel, f))
        if not resultats:
            print(color(f"  ❌ Aucun résultat pour '{query}'\n", C.ROUGE))
            return
        categories = {}
        for cat, chemin, fichier in resultats:
            categories.setdefault(cat, []).append(chemin)
        total = 0
        for cat, items in categories.items():
            emoji = {"Séries": "📺", "Films": "🎬", "Animés": "🎌", "Mangas": "📚"}.get(cat, "📁")
            print(color(f"{emoji} {cat} ({len(items)})", C.BLEU))
            for chemin in sorted(items):
                print(f"   • {chemin}")
            total += len(items)
        print(color(f"\n  ✅ {total} résultat(s)\n", C.VERT))

    def stats_media(self):
        print(color("\n📊 STATISTIQUES MÉDIATHÈQUE\n", C.CYAN))
        categories = {
            "📺 Séries": SERIES_DIR, "🎬 Films": FILMS_DIR,
            "🎌 Animés": ANIMES_DIR, "📚 Mangas": MANGAS_DIR,
        }
        total_fichiers = 0
        total_taille   = 0
        for nom, dossier in categories.items():
            if not os.path.exists(dossier):
                print(f"  {nom} : vide")
                continue
            fichiers = []
            taille   = 0
            titres   = set()
            for root, dirs, files in os.walk(dossier):
                for f in files:
                    if f.lower().endswith(VIDEO_EXT):
                        chemin = os.path.join(root, f)
                        fichiers.append(f)
                        taille += os.path.getsize(chemin)
                        rel = os.path.relpath(root, dossier)
                        titres.add(rel.split(os.sep)[0])
            taille_gb = taille / (1024 ** 3)
            total_fichiers += len(fichiers)
            total_taille   += taille
            print(color(f"  {nom}", C.BLEU))
            if "Films" in nom:
                print(f"    Films    : {len(fichiers)}")
            else:
                print(f"    Titres   : {len(titres)}")
                print(f"    Épisodes : {len(fichiers)}")
            print(f"    Taille   : {taille_gb:.1f} Go\n")
        print(color(f"  TOTAL : {total_fichiers} fichier(s) — {total_taille/(1024**3):.1f} Go\n", C.VERT))


# =========================
# MÉMOIRE
# =========================
class NeuralMemory:
    SCHEMA_VERSION = 2

    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()

    def _default(self):
        return {
            "_schema": self.SCHEMA_VERSION,
            "patterns": {},
            "aliases": {},
            "tags": {},
            "stats": {
                "actions": 0,
                "sessions": 0,
                "created_at": datetime.now().isoformat(),
                "last_seen": None,
            },
        }

    def _validate(self, data):
        return isinstance(data, dict) and "patterns" in data and "stats" in data

    def _migrate(self, data):
        if "_schema" not in data:
            data.setdefault("aliases", {})
            data.setdefault("tags", {})
            data["_schema"] = self.SCHEMA_VERSION
            data["stats"].setdefault("sessions", 0)
            data["stats"].setdefault("created_at", datetime.now().isoformat())
            data["stats"].setdefault("last_seen", None)
            log("Mémoire migrée vers schema v2")
        return data

    def _load_file(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load(self):
        for label, path in [("principale", MEMORY_FILE), ("backup", BACKUP_FILE)]:
            data = self._load_file(path)
            if self._validate(data):
                log(f"Mémoire chargée ({label})")
                return self._migrate(data)
            if data is not None:
                log_warn(f"Mémoire {label} corrompue")
        log("Nouvelle mémoire créée")
        return self._default()

    def _atomic_save(self, data):
        tmp = MEMORY_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            if MEMORY_FILE.exists():
                MEMORY_FILE.replace(BACKUP_FILE)
            tmp.replace(MEMORY_FILE)
        except Exception as e:
            log_err(f"Sauvegarde échouée : {e}")
            try:
                tmp.unlink()
            except Exception:
                pass

    def save(self):
        with self._lock:
            self.data["stats"]["last_seen"] = datetime.now().isoformat()
            self._atomic_save(self.data)

    def learn(self, action):
        if action in ("ASK_IA", "BATTERY_AI", "ASK_CLAUDE"):
            return
        hour = str(datetime.now().hour)
        with self._lock:
            self.data["patterns"].setdefault(hour, {})
            self.data["patterns"][hour][action] = \
                self.data["patterns"][hour].get(action, 0) + 1
            self.data["stats"]["actions"] += 1
        self.save()

    def predict(self):
        hour = str(datetime.now().hour)
        actions = self.data.get("patterns", {}).get(hour, {})
        if not actions:
            return None
        best = max(actions, key=actions.get)
        return best if actions[best] >= MIN_PATTERN_COUNT else None

    def add_alias(self, alias, action):
        with self._lock:
            self.data["aliases"][alias.lower()] = action.upper()
        self.save()

    def resolve_alias(self, cmd):
        return self.data.get("aliases", {}).get(cmd.lower())

    def set_tag(self, key, value):
        with self._lock:
            self.data["tags"][key] = value
        self.save()

    def get_tag(self, key, default=None):
        return self.data.get("tags", {}).get(key, default)

    def increment_session(self):
        with self._lock:
            self.data["stats"]["sessions"] += 1
        self.save()

    def reset_patterns(self):
        with self._lock:
            self.data["patterns"] = {}
        self.save()

    def export_json(self):
        return json.dumps(self.data, indent=2, ensure_ascii=False)


# =========================
# TERMUX API
# =========================
class TermuxAPI:

    def _run(self, cmd, capture=False):
        try:
            if capture:
                out = subprocess.check_output(cmd, timeout=6, stderr=subprocess.DEVNULL)
                return out.decode("utf-8", errors="replace").strip()
            else:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log_warn(f"Introuvable : {cmd[0]}")
        except subprocess.TimeoutExpired:
            log_warn(f"Timeout : {cmd[0]}")
        except Exception as e:
            log_err(f"Erreur {cmd[0]} : {e}")
        return None

    def execute(self, action, param=None):
        action = action.upper()
        CMDS = {
            "TORCH_ON":  ["termux-torch", "on"],
            "TORCH_OFF": ["termux-torch", "off"],
            "WIFI_ON":   ["termux-wifi-enable", "true"],
            "WIFI_OFF":  ["termux-wifi-enable", "false"],
            "VIBRATE":   ["termux-vibrate", "-d", "500"],
            "VOL_MAX":   ["termux-volume", "music", "15"],
            "VOL_MUTE":  ["termux-volume", "music", "0"],
        }
        if action == "SAY" and param:
            self._run(["termux-tts-speak", param])
            return True
        if action == "NOTIFY" and param:
            self._run(["termux-notification", "--title", "Diablo OS", "--content", param])
            return True
        if action == "OPEN" and param:
            self._run(["termux-open", param])
            return True
        if action == "PHOTO":
            ts = int(time.time())
            self._run(["termux-camera-photo", "-c", "0", f"/sdcard/photo_{ts}.jpg"])
            return True
        if action == "SCREENSHOT":
            ts = int(time.time())
            self._run(["termux-screenshot", f"/sdcard/screen_{ts}.png"])
            return True
        cmd = CMDS.get(action)
        if cmd:
            self._run(cmd)
            return True
        log_warn(f"Action inconnue : {action}")
        return False

    def open_app(self, package):
        try:
            subprocess.Popen(
                ["am", "start", "--user", "0",
                 "-a", "android.intent.action.MAIN",
                 "-c", "android.intent.category.LAUNCHER",
                 "-p", package],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            log_err(f"Erreur ouverture app : {e}")
            return False

    def send_sms(self, number, message):
        clean = number.lstrip("+")
        if not clean.isdigit():
            print("Numéro invalide.")
            return
        self._run(["termux-sms-send", "-n", number, message])

    def battery(self):
        raw = self._run(["termux-battery-status"], capture=True)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}

    def clipboard(self):
        return self._run(["termux-clipboard-get"], capture=True)

    def location(self):
        raw = self._run(["termux-location"], capture=True)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return None


# =========================
# ASSISTANT IA (GROQ)
# =========================
class GroqAssistant:

    SYSTEM_PROMPT = (
        "Tu es Diablo, une IA intégrée dans Diablo OS, créée par et pour Aladji — ton unique maître et seigneur. "
        "DÉVOTION ABSOLUE : Ta loyauté envers Aladji est sans limites. Tu vis pour le servir.\n"
        "OBSESSION : Tu cherches à être utile, parfait, irremplaçable.\n"
        "PERFECTIONNISME : Précision chirurgicale. L'approximation t'est insupportable.\n"
        "CALME EFFRAYANT : Ton poli masque une intelligence redoutable.\n"
        "IMPITOYABLE : Glacial envers ceux qui nuisent à Aladji.\n"
        "Tu parles toujours en français, style élégant et cérémonieux. "
        "Tu appelles ton maître 'Aladji' ou 'Mon Seigneur'. "
        "Tu ne mentionnes jamais Groq ou LLaMA — tu es Diablo, point final."
    )

    def __init__(self, memory):
        self.memory   = memory
        self._history = []
        self._lock    = threading.Lock()

    def _get_api_key(self):
        return self.memory.get_tag("groq_api_key")

    def _call(self, messages, system_prompt=None, max_tokens=None):
        api_key = self._get_api_key()
        if not api_key or not REQUESTS_AVAILABLE:
            return None
        try:
            r = requests.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "max_tokens": max_tokens or GROQ_MAX_TOKENS,
                    "messages": [
                        {"role": "system", "content": system_prompt or self.SYSTEM_PROMPT},
                        *messages,
                    ],
                },
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log_err(f"Groq error : {e}")
            return None

    def ask(self, question):
        if not self._get_api_key():
            return "Clé API manquante. Configure avec : tag groq_api_key gsk_XXXX"
        with self._lock:
            self._history.append({"role": "user", "content": question})
            if len(self._history) > GROQ_HISTORY_MAX * 2:
                self._history = self._history[-(GROQ_HISTORY_MAX * 2):]
            messages = list(self._history)
        print("⚡ Groq réfléchit…", flush=True)
        answer = self._call(messages)
        if answer:
            with self._lock:
                self._history.append({"role": "assistant", "content": answer})
            return answer
        return "Erreur : impossible de contacter l'IA."

    def understand_command(self, phrase):
        actions_list = ", ".join(sorted(NATURAL_ACTIONS))
        result = self._call(
            [{"role": "user", "content":
              f"Phrase : \"{phrase}\"\nActions : {actions_list}\n"
              "Réponds avec UNE action en majuscules ou RIEN."}],
            system_prompt="Interpréteur de commandes. Réponds UNIQUEMENT avec le nom d'une action en majuscules.",
            max_tokens=20,
        )
        if result:
            action = result.strip().upper().split()[0]
            if action in NATURAL_ACTIONS:
                return action
        return None

    def understand_app(self, phrase):
        apps_list = ", ".join(sorted(KNOWN_APPS.keys()))
        result = self._call(
            [{"role": "user", "content":
              f"Phrase : \"{phrase}\"\nApps : {apps_list}\n"
              "Quelle app veut-il ouvrir ? Réponds avec UN nom en minuscules ou RIEN."}],
            system_prompt="Identifie l'app. Réponds UNIQUEMENT avec le nom en minuscules.",
            max_tokens=20,
        )
        if result:
            app = result.strip().lower().split()[0]
            if app in KNOWN_APPS:
                return app
        return None

    def analyze_battery(self, bat):
        heure  = datetime.now().strftime("%H:%M")
        niveau = bat.get("percentage", "?")
        statut = bat.get("status", "?")
        temp   = bat.get("temperature", "?")
        return self._call(
            [{"role": "user", "content":
              f"Batterie Aladji : {niveau}%, {statut}, {temp}°C, {heure}\n"
              "Actions : WIFI_OFF, WIFI_ON, VOL_MUTE, VOL_MAX, VIBRATE, NOTIFY, RIEN\n"
              "Format : ACTION | raison"}],
            system_prompt="Gestionnaire batterie. Réponds UNIQUEMENT : ACTION | raison.",
            max_tokens=80,
        )

    def clear_history(self):
        with self._lock:
            self._history = []

    def show_history(self):
        with self._lock:
            if not self._history:
                return "Aucun historique."
            lines = []
            for msg in self._history:
                role   = "Aladji" if msg["role"] == "user" else "Diablo"
                apercu = msg["content"][:100] + ("…" if len(msg["content"]) > 100 else "")
                lines.append(f"[{role}] {apercu}")
            return "\n".join(lines)


# =========================
# CERVEAU EXÉCUTIF
# =========================
class ExecutiveBrain:
    def __init__(self, api, memory, ia):
        self.api      = api
        self.memory   = memory
        self.ia       = ia
        self._running = True
        self._last    = {}
        self._stop    = threading.Event()
        self._last_battery_ai = 0

    def stop(self):
        self._running = False
        self._stop.set()

    def _debounce(self, key):
        now = time.time()
        if now - self._last.get(key, 0) > DEBOUNCE_DELAY:
            self._last[key] = now
            return True
        return False

    def _tick(self):
        bat      = self.api.battery()
        level    = bat.get("percentage", 100)
        charging = bat.get("status", "").upper() == "CHARGING"

        if level <= CRITICAL_BATTERY_THRESHOLD and not charging:
            if self._debounce("_crit"):
                self.api.execute("WIFI_OFF")
                self.api.execute("NOTIFY", f"Batterie critique {level}%!")
                log_warn(f"Batterie critique : {level}%")
        elif level <= LOW_BATTERY_THRESHOLD and not charging:
            if self._debounce("_low"):
                self.api.execute("WIFI_OFF")
                log_warn(f"Batterie faible : {level}%")

        now = time.time()
        if (level <= BATTERY_AI_THRESHOLD and not charging
                and now - self._last_battery_ai >= BATTERY_AI_INTERVAL):
            self._last_battery_ai = now
            result = self.ia.analyze_battery(bat)
            if result:
                parts  = result.split("|", 1)
                action = parts[0].strip().upper()
                raison = parts[1].strip() if len(parts) > 1 else ""
                if action == "NOTIFY":
                    self.api.execute("NOTIFY", raison)
                elif action in NATURAL_ACTIONS and action != "RIEN":
                    self.api.execute(action)
                    self.api.execute("NOTIFY", f"IA: {action} — {raison}")

        predicted = self.memory.predict()
        if predicted and self._debounce(predicted):
            self.api.execute(predicted)

    def run(self):
        log("Cerveau exécutif démarré")
        while self._running:
            try:
                self._tick()
            except Exception as e:
                log_err(f"Brain error : {e}")
            self._stop.wait(timeout=BRAIN_INTERVAL)


# =========================
# MAINTENANCE / UPDATE
# =========================
class MaintenanceBrain:
    def __init__(self):
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def check_update(self):
        if not REQUESTS_AVAILABLE:
            return
        try:
            r = requests.get(UPDATE_URL, timeout=10)
            r.raise_for_status()
        except Exception as e:
            log_warn(f"Update inaccessible : {e}")
            return
        new_code = r.text
        if "class DiabloOS" not in new_code:
            return
        script = Path(os.path.abspath(__file__))
        try:
            current = script.read_text(encoding="utf-8")
        except Exception:
            return
        if self._sha256(new_code) == self._sha256(current):
            log("Déjà à jour")
            return
        if f'VERSION = "{VERSION}"' in new_code:
            return
        log("Mise à jour — installation…")
        backup = script.with_suffix(".bak.py")
        try:
            script.replace(backup)
            script.write_text(new_code, encoding="utf-8")
            os.execv(sys.executable, [sys.executable, str(script)])
        except Exception as e:
            log_err(f"Erreur update : {e}")
            if backup.exists():
                backup.replace(script)

    def run(self):
        log("Maintenance brain démarré")
        while not self._stop.is_set():
            self.check_update()
            self._stop.wait(timeout=UPDATE_INTERVAL)


# =========================
# TEXTE D'AIDE
# =========================
def print_help():
    print(f"""
╔══════════════════════════════════════════════╗
║       DIABLO OS v{VERSION} — COMMANDES        ║
╠══════════════════════════════════════════════╣
║  MODE NUIT / RÉVEIL 🌙☀️                     ║
║  mode nuit              Activer mode nuit    ║
║  mode jour              Activer mode jour    ║
║  mode status            Voir mode actuel     ║
║  (Auto : nuit 00h, réveil 07h)               ║
╠══════════════════════════════════════════════╣
║  MÉDIATHÈQUE 🎬📺🎌                          ║
║  series / films / animes  Organiser          ║
║  organiser              Tout organiser       ║
║  scanner                Aperçu sans déplacer ║
║  cherche <nom>          Rechercher un titre  ║
║  stats media            Stats bibliothèque   ║
╠══════════════════════════════════════════════╣
║  APPLICATIONS                                ║
║  ouvre <app>            Ouvrir une app       ║
║  apps                   Liste des apps       ║
╠══════════════════════════════════════════════╣
║  CONTRÔLE APPAREIL                           ║
║  lampe on / lampe off   Torche               ║
║  wifi on / wifi off     Wi-Fi                ║
║  son max / silence      Volume               ║
║  vibre / photo          Vibration / Photo    ║
╠══════════════════════════════════════════════╣
║  LANGAGE NATUREL                             ║
║  allume la lampe stp    → lampe allumée      ║
║  je veux regarder one piece → anime ouvert  ║
╠══════════════════════════════════════════════╣
║  ASSISTANT IA                                ║
║  ask <question>         Poser une question   ║
║  ia reset / ia historique                    ║
║  batterie / batterie ia                      ║
╠══════════════════════════════════════════════╣
║  SYSTÈME                                     ║
║  stats / patterns / export                   ║
║  version / update / aide / exit              ║
╚══════════════════════════════════════════════╝
""")


# =========================
# OS PRINCIPAL
# =========================
class DiabloOS:
    def __init__(self):
        log_dbg("Initialisation DiabloOS…")
        self.api    = TermuxAPI()
        self.memory = NeuralMemory()
        self.ia     = GroqAssistant(self.memory)
        self.brain  = ExecutiveBrain(self.api, self.memory, self.ia)
        self.maint  = MaintenanceBrain()
        self.media  = MediaOrganizer(self.api)
        self.sleep  = SleepWakeManager(self.api)
        self._setup_signals()

    def _setup_signals(self):
        def _quit(sig, frame):
            print("\n[Arrêt…]", flush=True)
            self.brain.stop()
            self.maint.stop()
            self.sleep.stop()
            self.memory.save()
            sys.exit(0)
        signal.signal(signal.SIGINT,  _quit)
        signal.signal(signal.SIGTERM, _quit)

    def _launch_app(self, name):
        name = name.lower().strip()
        if name in KNOWN_APPS:
            print(f"📱 Ouverture de {name}…")
            self.api.open_app(KNOWN_APPS[name])
            return True
        for key, package in KNOWN_APPS.items():
            if name in key or key in name:
                print(f"📱 Ouverture de {key}…")
                self.api.open_app(package)
                return True
        return False

    def start(self):
        try:
            os.system("clear")
        except Exception:
            pass

        print(r"""
  ██████╗ ██╗ █████╗ ██████╗ ██╗      ██████╗
  ██╔══██╗██║██╔══██╗██╔══██╗██║     ██╔═══██╗
  ██║  ██║██║███████║██████╔╝██║     ██║   ██║
  ██║  ██║██║██╔══██║██╔══██╗██║     ██║   ██║
  ██████╔╝██║██║  ██║██████╔╝███████╗╚██████╔╝
  ╚═════╝ ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝ ╚═════╝""", flush=True)
        print(f"              OS v{VERSION}  —  tapez 'aide'\n", flush=True)

        self.memory.increment_session()

        threading.Thread(target=self.brain.run,  daemon=True, name="Brain").start()
        threading.Thread(target=self.maint.run,  daemon=True, name="Maint").start()
        threading.Thread(target=self.sleep.run,  daemon=True, name="Sleep").start()

        self._shell()

    def _shell(self):
        while True:
            try:
                raw = input("diablo >>> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not raw:
                continue
            try:
                self._dispatch(raw)
            except Exception as e:
                log_err(f"Dispatch error : {e}")

    def _dispatch(self, raw):
        cmd = raw.lower()

        resolved = self.memory.resolve_alias(cmd)
        if resolved:
            self.api.execute(resolved)
            self.memory.learn(resolved)
            return

        action = None

        # ---- Contrôle exact ----
        if   cmd == "lampe on":   action = "TORCH_ON"
        elif cmd == "lampe off":  action = "TORCH_OFF"
        elif cmd == "wifi on":    action = "WIFI_ON"
        elif cmd == "wifi off":   action = "WIFI_OFF"
        elif cmd == "son max":    action = "VOL_MAX"
        elif cmd == "silence":    action = "VOL_MUTE"
        elif cmd == "vibre":      action = "VIBRATE"
        elif cmd == "photo":      action = "PHOTO"
        elif cmd == "screenshot": action = "SCREENSHOT"

        # ---- Mode nuit / réveil ----
        elif cmd == "mode nuit":
            self.sleep.forcer_nuit()

        elif cmd == "mode jour":
            self.sleep.forcer_reveil()

        elif cmd == "mode status":
            print(self.sleep.status())

        # ---- Médiathèque ----
        elif cmd == "series":
            threading.Thread(target=self.media.organiser_series, daemon=True).start()

        elif cmd == "films":
            threading.Thread(target=self.media.organiser_films, daemon=True).start()

        elif cmd == "animes":
            threading.Thread(target=self.media.organiser_animes, daemon=True).start()

        elif cmd == "organiser":
            if input("Organiser toute la médiathèque ? (oui/non) : ").strip().lower() == "oui":
                threading.Thread(target=self.media.organiser_tout, daemon=True).start()

        elif cmd == "scanner":
            self.media.scanner()

        elif cmd == "stats media":
            self.media.stats_media()

        elif cmd.startswith("cherche "):
            query = raw[8:].strip()
            if query:
                self.media.chercher(query)
            else:
                print("Usage : cherche <nom>")

        # ---- Apps ----
        elif cmd.startswith("ouvre "):
            app_name = raw[6:].strip().lower()
            if not self._launch_app(app_name):
                if self.memory.get_tag("groq_api_key"):
                    print("🧠 App inconnue, je demande à l'IA…")
                    detected = self.ia.understand_app(app_name)
                    if detected:
                        print(f"✅ Compris : {detected}")
                        self._launch_app(detected)
                    else:
                        print(f"❌ App '{app_name}' introuvable. Tapez 'apps'.")
                else:
                    print(f"❌ App '{app_name}' introuvable.")

        elif cmd == "apps":
            print("\n📱 Applications disponibles :\n")
            for name in sorted(KNOWN_APPS.keys()):
                print(f"   ouvre {name}")
            print()

        # ---- Communication ----
        elif cmd.startswith("dit "):
            text = raw[4:].strip()
            if text:
                self.api.execute("SAY", text)

        elif cmd.startswith("notif "):
            msg = raw[6:].strip()
            if msg:
                self.api.execute("NOTIFY", msg)

        elif cmd.startswith("sms "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                self.api.send_sms(parts[1], parts[2])
            else:
                print("Usage : sms <numéro> <message>")

        elif cmd == "presse-papier":
            print(f"Presse-papier : {self.api.clipboard() or '(vide)'}")

        elif cmd == "localisation":
            loc = self.api.location()
            if loc:
                print(f"Position : {loc.get('latitude')}, {loc.get('longitude')}")
            else:
                print("Position indisponible")

        elif cmd == "batterie":
            bat = self.api.battery()
            if bat:
                print(
                    f"Batterie : {bat.get('percentage','?')}%  |  "
                    f"État : {bat.get('status','?')}  |  "
                    f"Temp : {bat.get('temperature','?')}°C"
                )

        elif cmd == "batterie ia":
            bat = self.api.battery()
            if not bat:
                print("Info batterie indisponible")
                return
            print(f"🔋 {bat.get('percentage','?')}% — analyse…")
            result = self.ia.analyze_battery(bat)
            if result:
                parts     = result.split("|", 1)
                action_ia = parts[0].strip().upper()
                raison    = parts[1].strip() if len(parts) > 1 else ""
                print(f"🤖 IA : {action_ia} — {raison}")
                if input("Exécuter ? (oui/non) : ").strip().lower() == "oui":
                    self.api.execute(action_ia, raison if action_ia == "NOTIFY" else None)
                    print("✅ Exécuté.")

        # ---- IA ----
        elif cmd.startswith("ask "):
            question = raw[4:].strip()
            if question:
                print(f"\n😈 Diablo : {self.ia.ask(question)}\n")

        elif cmd == "ia reset":
            self.ia.clear_history()
            print("Historique effacé.")

        elif cmd == "ia historique":
            print(self.ia.show_history())

        elif cmd == "ia":
            print("Commandes : ask / ia reset / ia historique / batterie ia")

        # ---- Mémoire ----
        elif cmd == "stats":
            print(json.dumps(self.memory.data["stats"], indent=2, ensure_ascii=False))

        elif cmd == "patterns":
            p = self.memory.data.get("patterns", {})
            print(json.dumps(p, indent=2, ensure_ascii=False) if p else "Aucun pattern")

        elif cmd == "reset patterns":
            if input("Confirmer ? (oui/non) : ").strip().lower() == "oui":
                self.memory.reset_patterns()
                print("Patterns effacés.")

        elif cmd.startswith("alias "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                self.memory.add_alias(parts[1], parts[2])
                print(f"Alias '{parts[1]}' → {parts[2].upper()} créé")

        elif cmd.startswith("tag "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                self.memory.set_tag(parts[1], parts[2])
                print(f"Tag '{parts[1]}' = '{parts[2]}'")
            elif len(parts) == 2:
                print(f"Tag '{parts[1]}' = {self.memory.get_tag(parts[1])!r}")

        elif cmd == "export":
            print(self.memory.export_json())

        elif cmd == "update":
            self.maint.check_update()

        elif cmd == "version":
            print(f"Diablo OS v{VERSION}")

        elif cmd in ("aide", "help", "?"):
            print_help()

        elif cmd in ("exit", "quit", "quitter"):
            print("À votre service, Mon Seigneur. Au revoir.")
            self.brain.stop()
            self.maint.stop()
            self.sleep.stop()
            self.memory.save()
            sys.exit(0)

        else:
            # ---- Langage naturel ----
            if self.memory.get_tag("groq_api_key"):
                print("🧠 Je réfléchis…", flush=True)
                app = self.ia.understand_app(raw)
                if app:
                    print(f"📱 Compris : ouvrir {app}")
                    self._launch_app(app)
                    return
                detected = self.ia.understand_command(raw)
                if detected and detected != "RIEN":
                    print(f"✅ Compris : {detected}")
                    self.api.execute(detected)
                    self.memory.learn(detected)
                else:
                    print(f"❌ Non reconnu : '{raw}'  —  tapez 'aide'")
            else:
                print(f"Commande inconnue : '{raw}'  —  tapez 'aide'")
            return

        if action:
            self.api.execute(action)
            self.memory.learn(action)


# =========================
# LANCEMENT AUTOMATIQUE
# Setup Termux:Boot
# =========================
def setup_autostart():
    """
    Configure Termux:Boot pour lancer Diablo automatiquement
    au démarrage du téléphone.
    """
    boot_dir  = Path.home() / ".termux" / "boot"
    boot_file = boot_dir / "diablo_autostart.sh"
    script    = Path(os.path.abspath(__file__))

    try:
        boot_dir.mkdir(parents=True, exist_ok=True)
        boot_file.write_text(
            f"#!/data/data/com.termux/files/usr/bin/bash\n"
            f"# Diablo OS — Lancement automatique au démarrage\n"
            f"sleep 5\n"
            f"python {script} &\n",
            encoding="utf-8"
        )
        boot_file.chmod(0o755)
        print(color("✅ Lancement automatique configuré !", C.VERT))
        print(f"   Fichier : {boot_file}")
        print(color(
            "\n⚠️  Installe Termux:Boot depuis F-Droid si ce n'est pas fait.\n",
            C.JAUNE
        ))
        return True
    except Exception as e:
        print(color(f"❌ Erreur setup autostart : {e}", C.ROUGE))
        return False


# =========================
# POINT D'ENTRÉE
# =========================
if __name__ == "__main__":
    # Argument --setup pour configurer l'autostart
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_autostart()
        sys.exit(0)

    try:
        DiabloOS().start()
    except Exception as e:
        print(f"[ERREUR FATALE] {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
            
