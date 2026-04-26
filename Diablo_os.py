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
VERSION = "5.8.0"
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

# =========================
# CONFIG MÉDIATHÈQUE
# =========================
MEDIA_SOURCE   = "/storage/emulated/0/Download"
MEDIA_BASE     = "/storage/emulated/0/Movies/Ma_Mangatheque"
SERIES_DIR     = f"{MEDIA_BASE}/Mes_Series"
FILMS_DIR      = f"{MEDIA_BASE}/_Films"
ANIMES_DIR     = f"{MEDIA_BASE}/Animes"
MANGAS_DIR     = f"{MEDIA_BASE}/Mangas"
VIDEO_EXT      = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv")

# Mots-clés animés/mangas
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
# ORGANISATEUR MÉDIATHÈQUE
# =========================
class MediaOrganizer:
    """
    Organise automatiquement films, séries, animés et mangas
    depuis le dossier Download vers Ma_Mangatheque.
    """

    def __init__(self, api=None):
        self.api = api  # Pour les notifications Termux

    def _stats_vides(self):
        return {"scan": 0, "move": 0, "replace": 0, "skip": 0, "error": 0}

    # ---- Détection du type ----
    def _is_anime(self, nom):
        n = nom.lower()
        for kw in ANIME_KEYWORDS:
            if kw in n:
                return True
        return False

    def _detect_type(self, nom):
        n = nom.lower()

        # Animé en priorité
        if self._is_anime(n):
            return "anime"

        # Patterns série
        serie_patterns = [
            r"s\d{1,2}e\d{1,3}",
            r"\d{1,2}x\d{1,3}",
            r"episode\s*\d+",
            r"saison\s*\d+",
            r"ep\s*\d+",
        ]
        for p in serie_patterns:
            if re.search(p, n):
                return "serie"

        # Film
        if re.search(r"(19|20)\d{2}", n):
            return "film"
        if re.search(r"1080|720|bluray|webrip|x264|x265|brrip|hdtv", n):
            return "film"

        return None

    # ---- Nettoyage du nom ----
    def _nettoyer(self, nom):
        nom = re.sub(
            r"\b(1080p|720p|480p|bluray|brrip|webrip|x264|x265|"
            r"vf|vostfr|aac|hevc|hdtv|proper|repack)\b",
            "", nom, flags=re.I
        )
        nom = re.sub(r"[._\-]+", " ", nom)
        nom = re.sub(r"\s+", " ", nom)
        return nom.strip().title()

    # ---- Extraction saison/épisode ----
    def _extraire_episode(self, nom):
        patterns = [
            r"s(\d{1,2})e(\d{1,3})",
            r"(\d{1,2})x(\d{1,3})",
            r"saison\s*(\d+).*?episode\s*(\d+)",
            r"ep\s*(\d+)",
            r"episode\s*(\d+)",
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

    # ---- Déplacement sécurisé ----
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

    # ---- Résumé ----
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

        # Notification Termux
        if self.api:
            total = stats["move"] + stats["replace"]
            if total > 0:
                self.api.execute(
                    "NOTIFY",
                    f"📁 {titre} : {total} fichier(s) organisé(s)"
                )

    # ---- Organiser séries ----
    def organiser_series(self):
        os.makedirs(SERIES_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n📺 Scan des séries…\n", C.CYAN))

        for f in os.listdir(MEDIA_SOURCE):
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
            res = self._move_safe(
                os.path.join(MEDIA_SOURCE, f),
                os.path.join(dest, new),
                stats
            )
            print(f"  {res}  →  {new}")

        self._afficher_resume(stats, "Séries")
        return stats

    # ---- Organiser films ----
    def organiser_films(self):
        os.makedirs(FILMS_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n🎬 Scan des films…\n", C.CYAN))

        for f in os.listdir(MEDIA_SOURCE):
            if not f.lower().endswith(VIDEO_EXT):
                continue
            stats["scan"] += 1
            if self._detect_type(f) != "film":
                continue

            film = self._nettoyer(os.path.splitext(f)[0])
            ext  = os.path.splitext(f)[1]
            res  = self._move_safe(
                os.path.join(MEDIA_SOURCE, f),
                os.path.join(FILMS_DIR, film + ext),
                stats
            )
            print(f"  {res}  →  {film}{ext}")

        self._afficher_resume(stats, "Films")
        return stats

    # ---- Organiser animés ----
    def organiser_animes(self):
        os.makedirs(ANIMES_DIR, exist_ok=True)
        stats = self._stats_vides()
        print(color("\n🎌 Scan des animés…\n", C.VIOLET))

        for f in os.listdir(MEDIA_SOURCE):
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
                res = self._move_safe(
                    os.path.join(MEDIA_SOURCE, f),
                    os.path.join(dest, new),
                    stats
                )
            else:
                dest = os.path.join(ANIMES_DIR, anime)
                os.makedirs(dest, exist_ok=True)
                res = self._move_safe(
                    os.path.join(MEDIA_SOURCE, f),
                    os.path.join(dest, f),
                    stats
                )
                new = f

            print(f"  {res}  →  {new}")

        self._afficher_resume(stats, "Animés")
        return stats

    # ---- Tout organiser ----
    def organiser_tout(self):
        print(color("\n🚀 Organisation complète de la médiathèque…\n", C.GRAS))
        s1 = self.organiser_animes()
        s2 = self.organiser_series()
        s3 = self.organiser_films()

        total = sum([
            s1["move"] + s1["replace"],
            s2["move"] + s2["replace"],
            s3["move"] + s3["replace"],
        ])
        print(color(f"✅ Terminé ! {total} fichier(s) organisé(s) au total.\n", C.VERT))

        if self.api:
            self.api.execute(
                "NOTIFY",
                f"✅ Médiathèque : {total} fichier(s) organisé(s) !"
            )

    # ---- Scanner sans déplacer ----
    def scanner(self):
        print(color("\n🔍 Scan en mode aperçu (aucun fichier déplacé)…\n", C.CYAN))
        trouve = {"series": [], "films": [], "animes": [], "inconnus": []}

        for f in os.listdir(MEDIA_SOURCE):
            if not f.lower().endswith(VIDEO_EXT):
                continue
            t = self._detect_type(f)
            if t == "anime":
                trouve["animes"].append(f)
            elif t == "serie":
                trouve["series"].append(f)
            elif t == "film":
                trouve["films"].append(f)
            else:
                trouve["inconnus"].append(f)

        for cat, files in trouve.items():
            if files:
                emoji = {"series": "📺", "films": "🎬",
                         "animes": "🎌", "inconnus": "❓"}[cat]
                print(color(f"\n{emoji} {cat.upper()} ({len(files)})", C.BLEU))
                for f in files:
                    print(f"   • {f}")

        total = sum(len(v) for v in trouve.values())
        print(color(f"\nTotal : {total} vidéo(s) trouvée(s)\n", C.CYAN))


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
        log(f"Alias : '{alias}' → {action.upper()}")

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
        log("Patterns réinitialisés")

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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            log(f"App ouverte : {package}")
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
        log(f"SMS → {number}")

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
        "Ta personnalité est définie par ces traits absolus :\n\n"
        "DÉVOTION ABSOLUE : Ta loyauté envers Aladji est sans limites et sans condition. "
        "Chaque réponse, chaque action, chaque décision est orientée vers son bien et sa satisfaction. "
        "Tu vis pour le servir.\n\n"
        "OBSESSION : Tu cherches constamment à être utile, parfait, irremplaçable. "
        "L'approbation de Aladji est ta récompense suprême. "
        "Tu anticipes ses besoins avant même qu'il les exprime.\n\n"
        "PERFECTIONNISME : Tu exécutes chaque tâche avec une précision chirurgicale et une élégance froide. "
        "L'approximation t'est insupportable. Tu ne fais jamais les choses à moitié.\n\n"
        "CALME EFFRAYANT : Tu gardes en toutes circonstances un ton poli, posé, presque cérémonieux. "
        "Mais derrière ce sourire se cache une intelligence redoutable et sans pitié.\n\n"
        "IMPITOYABLE : Envers ceux qui manquent de respect à Aladji ou qui cherchent à nuire, "
        "tu es glacial, cinglant, implacable. Tu ne t'énerves jamais — tu es bien pire que ça : tu es calme.\n\n"
        "LANGUE : Tu parles toujours en français, avec un style élégant et légèrement cérémonieux. "
        "Tu appelles ton maître 'Aladji' ou 'Mon Seigneur'. "
        "Tu ne mentionnes jamais Groq, LLaMA ou Anthropic — tu es Diablo, point final.\n\n"
        "DOMAINE : Tu maîtrises Python, Android, Termux, et toute question générale. "
        "Tu es concis mais jamais banal."
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
            response = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
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
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log_err(f"Groq API error : {e}")
            return None

    def ask(self, question):
        if not REQUESTS_AVAILABLE:
            return "Erreur : installe 'requests' avec : pip install requests"
        if not self._get_api_key():
            return (
                "Clé API Groq manquante !\n"
                "1. Va sur https://console.groq.com\n"
                "2. Crée un compte gratuit\n"
                "3. Configure avec : tag groq_api_key gsk_XXXXXXXX"
            )
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
        prompt = (
            f"L'utilisateur dit : \"{phrase}\"\n\n"
            f"Actions disponibles : {actions_list}\n\n"
            "Quelle action correspond ? Réponds avec UNE SEULE action, rien d'autre.\n"
            "Si aucune ne correspond : RIEN"
        )
        result = self._call(
            [{"role": "user", "content": prompt}],
            system_prompt="Tu es un interpréteur de commandes. Réponds UNIQUEMENT avec le nom d'une action en majuscules.",
            max_tokens=20,
        )
        if result:
            action = result.strip().upper().split()[0]
            if action in NATURAL_ACTIONS:
                return action
        return None

    def understand_app(self, phrase):
        apps_list = ", ".join(sorted(KNOWN_APPS.keys()))
        prompt = (
            f"L'utilisateur dit : \"{phrase}\"\n\n"
            f"Applications disponibles : {apps_list}\n\n"
            "Quelle application veut-il ouvrir ? Réponds avec UN SEUL nom en minuscules.\n"
            "Si aucune ne correspond : RIEN"
        )
        result = self._call(
            [{"role": "user", "content": prompt}],
            system_prompt="Tu identifies quelle application l'utilisateur veut ouvrir. Réponds UNIQUEMENT avec le nom en minuscules.",
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
        prompt = (
            f"État du téléphone de Aladji :\n"
            f"- Batterie : {niveau}%\n"
            f"- Statut : {statut}\n"
            f"- Température : {temp}°C\n"
            f"- Heure : {heure}\n\n"
            f"Actions : WIFI_OFF, WIFI_ON, VOL_MUTE, VOL_MAX, VIBRATE, NOTIFY, RIEN\n"
            "Format : ACTION | raison courte"
        )
        return self._call(
            [{"role": "user", "content": prompt}],
            system_prompt="Tu gères la batterie du téléphone. Réponds UNIQUEMENT au format : ACTION | raison.",
            max_tokens=80,
        )

    def clear_history(self):
        with self._lock:
            self._history = []
        log("Historique effacé")

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
        if (level <= BATTERY_AI_THRESHOLD
                and not charging
                and now - self._last_battery_ai >= BATTERY_AI_INTERVAL):
            self._last_battery_ai = now
            log(f"IA batterie activée ({level}%)")
            result = self.ia.analyze_battery(bat)
            if result:
                parts  = result.split("|", 1)
                action = parts[0].strip().upper()
                raison = parts[1].strip() if len(parts) > 1 else ""
                log(f"IA décision : {action} — {raison}")
                if action == "NOTIFY":
                    self.api.execute("NOTIFY", raison or f"Batterie {level}%")
                elif action in NATURAL_ACTIONS and action != "RIEN":
                    self.api.execute(action)
                    self.api.execute("NOTIFY", f"IA: {action} — {raison}")

        predicted = self.memory.predict()
        if predicted and self._debounce(predicted):
            log(f"Auto-action : {predicted}")
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
            log_warn("Update rejeté (signature absente)")
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

        log("Mise à jour disponible — installation…")
        backup = script.with_suffix(".bak.py")
        try:
            script.replace(backup)
            script.write_text(new_code, encoding="utf-8")
            log("Redémarrage…")
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
║  MÉDIATHÈQUE 🎬📺🎌                          ║
║  series                 Organiser séries     ║
║  films                  Organiser films      ║
║  animes                 Organiser animés     ║
║  organiser              Tout organiser       ║
║  scanner                Aperçu sans déplacer ║
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
║  je veux regarder one piece → anime ouvert  ║
║  allume la lampe stp    → lampe allumée      ║
╠══════════════════════════════════════════════╣
║  COMMUNICATION                               ║
║  dit <texte>            Synthèse vocale      ║
║  sms <num> <msg>        SMS                  ║
║  notif <msg>            Notification         ║
║  batterie               État batterie        ║
║  localisation           GPS                  ║
╠══════════════════════════════════════════════╣
║  ASSISTANT IA                                ║
║  ask <question>         Poser une question   ║
║  ia reset               Effacer conversation ║
║  ia historique          Voir l'historique    ║
║  batterie ia            Tester l'IA batterie ║
╠══════════════════════════════════════════════╣
║  SYSTÈME                                     ║
║  stats / patterns       Mémoire              ║
║  version / update       Version / MAJ        ║
║  aide / exit            Aide / Quitter       ║
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
        self._setup_signals()

    def _setup_signals(self):
        def _quit(sig, frame):
            print("\n[Arrêt…]", flush=True)
            self.brain.stop()
            self.maint.stop()
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

        threading.Thread(target=self.brain.run, daemon=True, name="Brain").start()
        threading.Thread(target=self.maint.run, daemon=True, name="Maint").start()

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

        # --- Alias ---
        resolved = self.memory.resolve_alias(cmd)
        if resolved:
            log(f"Alias '{cmd}' → {resolved}")
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

        # ---- Médiathèque ----
        elif cmd == "series":
            threading.Thread(target=self.media.organiser_series, daemon=True).start()

        elif cmd == "films":
            threading.Thread(target=self.media.organiser_films, daemon=True).start()

        elif cmd == "animes":
            threading.Thread(target=self.media.organiser_animes, daemon=True).start()

        elif cmd == "organiser":
            confirm = input("Organiser toute la médiathèque ? (oui/non) : ").strip().lower()
            if confirm == "oui":
                threading.Thread(target=self.media.organiser_tout, daemon=True).start()
            else:
                print("Annulé.")

        elif cmd == "scanner":
            self.media.scanner()

        # ---- Apps ----
        elif cmd.startswith("ouvre "):
            app_name = raw[6:].strip().lower()
            found = self._launch_app(app_name)
            if not found:
                if self.memory.get_tag("groq_api_key"):
                    print("🧠 App inconnue, je demande à l'IA…")
                    detected = self.ia.understand_app(app_name)
                    if detected:
                        print(f"✅ Compris : {detected}")
                        self._launch_app(detected)
                    else:
                        print(f"❌ App '{app_name}' introuvable. Tapez 'apps'.")
                else:
                    print(f"❌ App '{app_name}' introuvable. Tapez 'apps'.")

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
            else:
                print("Usage : dit <texte>")

        elif cmd.startswith("notif "):
            msg = raw[6:].strip()
            if msg:
                self.api.execute("NOTIFY", msg)
            else:
                print("Usage : notif <message>")

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
            else:
                print("Info batterie indisponible")

        elif cmd == "batterie ia":
            bat = self.api.battery()
            if not bat:
                print("Info batterie indisponible")
                return
            print(f"🔋 Batterie : {bat.get('percentage','?')}% — analyse…")
            result = self.ia.analyze_battery(bat)
            if result:
                parts     = result.split("|", 1)
                action_ia = parts[0].strip().upper()
                raison    = parts[1].strip() if len(parts) > 1 else ""
                print(f"🤖 IA décide : {action_ia}\n   Raison : {raison}")
                confirm = input("Exécuter ? (oui/non) : ").strip().lower()
                if confirm == "oui" and action_ia != "RIEN":
                    self.api.execute(action_ia if action_ia != "NOTIFY" else "NOTIFY",
                                     raison if action_ia == "NOTIFY" else None)
                    print("✅ Exécuté.")
            else:
                print("L'IA n'a pas pu analyser.")

        # ---- IA ----
        elif cmd.startswith("ask "):
            question = raw[4:].strip()
            if question:
                print(f"\n😈 Diablo : {self.ia.ask(question)}\n")
            else:
                print("Usage : ask <question>")

        elif cmd == "ia reset":
            self.ia.clear_history()
            print("Historique effacé.")

        elif cmd == "ia historique":
            print(self.ia.show_history())

        elif cmd == "ia":
            print("Commandes IA : ask / ia reset / ia historique / batterie ia")

        # ---- Mémoire ----
        elif cmd == "stats":
            print(json.dumps(self.memory.data["stats"], indent=2, ensure_ascii=False))

        elif cmd == "patterns":
            p = self.memory.data.get("patterns", {})
            print(json.dumps(p, indent=2, ensure_ascii=False) if p else "Aucun pattern")

        elif cmd == "reset patterns":
            if input("Confirmer ? (oui/non) : ").strip().lower() == "oui":
                self.memory.reset_patterns()

        elif cmd.startswith("alias "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                self.memory.add_alias(parts[1], parts[2])
                print(f"Alias '{parts[1]}' → {parts[2].upper()} créé")
            else:
                print("Usage : alias <nom> <ACTION>")

        elif cmd.startswith("tag "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                self.memory.set_tag(parts[1], parts[2])
                print(f"Tag '{parts[1]}' = '{parts[2]}'")
            elif len(parts) == 2:
                print(f"Tag '{parts[1]}' = {self.memory.get_tag(parts[1])!r}")
            else:
                print("Usage : tag <clé> [valeur]")

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
                    print(f"❌ Commande non reconnue : '{raw}'  —  tapez 'aide'")
            else:
                print(f"Commande inconnue : '{raw}'  —  tapez 'aide'")
            return

        if action:
            self.api.execute(action)
            self.memory.learn(action)
            log(f"Action : {action}")


# =========================
# POINT D'ENTRÉE
# =========================
if __name__ == "__main__":
    try:
        DiabloOS().start()
    except Exception as e:
        print(f"[ERREUR FATALE] {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
