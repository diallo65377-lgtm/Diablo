import os
import sys
import json
import time
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
VERSION = "5.7.0"
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
GROQ_MODEL     = "llama-3.1-8b-instant"
GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
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

# =========================
# APPS CONNUES
# Nom reconnu → package Android
# =========================
KNOWN_APPS = {
    # Réseaux sociaux
    "youtube":      "com.google.android.youtube",
    "whatsapp":     "com.whatsapp",
    "tiktok":       "com.zhiliaoapp.musically",
    "instagram":    "com.instagram.android",
    "facebook":     "com.facebook.katana",
    "twitter":      "com.twitter.android",
    "telegram":     "org.telegram.messenger",
    "snapchat":     "com.snapchat.android",

    # Google
    "chrome":       "com.android.chrome",
    "maps":         "com.google.android.apps.maps",
    "gmail":        "com.google.android.gm",
    "drive":        "com.google.android.apps.docs",
    "play":         "com.android.vending",
    "meet":         "com.google.android.apps.meetings",

    # Système Android
    "parametres":   "com.android.settings",
    "paramètres":   "com.android.settings",
    "camera":       "com.android.camera2",
    "caméra":       "com.android.camera2",
    "galerie":      "com.android.gallery3d",
    "contacts":     "com.android.contacts",
    "telephone":    "com.android.dialer",
    "téléphone":    "com.android.dialer",
    "sms":          "com.android.mms",
    "calculatrice": "com.android.calculator2",
    "horloge":      "com.android.deskclock",
    "agenda":       "com.android.calendar",
    "fichiers":     "com.android.documentsui",
    "musique":      "com.android.music",

    # Autres
    "spotify":      "com.spotify.music",
    "netflix":      "com.netflix.mediaclient",
    "amazon":       "com.amazon.mShop.android.shopping",
    "termux":       "com.termux",
}


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

logger  = setup_logging()
log      = logger.info
log_warn = logger.warning
log_err  = logger.error
log_dbg  = logger.debug


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
                out = subprocess.check_output(
                    cmd, timeout=6,
                    stderr=subprocess.DEVNULL
                )
                return out.decode("utf-8", errors="replace").strip()
            else:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except FileNotFoundError:
            log_warn(f"Introuvable : {cmd[0]}  (termux-api installé ?)")
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
            self._run(["termux-notification",
                       "--title", "Diablo OS",
                       "--content", param])
            return True
        if action == "OPEN" and param:
            self._run(["termux-open", param])
            return True
        if action == "PHOTO":
            ts = int(time.time())
            self._run(["termux-camera-photo", "-c", "0",
                       f"/sdcard/photo_{ts}.jpg"])
            return True
        if action == "SCREENSHOT":
            ts = int(time.time())
            self._run(["termux-screenshot",
                       f"/sdcard/screen_{ts}.png"])
            return True

        cmd = CMDS.get(action)
        if cmd:
            self._run(cmd)
            return True

        log_warn(f"Action inconnue : {action}")
        return False

    def open_app(self, package):
        """Ouvre une application Android par son nom de package."""
        try:
            subprocess.Popen(
                ["am", "start", "-n",
                 f"{package}/{package}.MainActivity"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Si la première méthode échoue, essaie avec monkey
            time.sleep(0.5)
            subprocess.Popen(
                ["monkey", "-p", package, "-c",
                 "android.intent.category.LAUNCHER", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
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
                "3. Va dans API Keys > Create API Key\n"
                "4. Configure avec : tag groq_api_key gsk_XXXXXXXX"
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
        """Comprend une phrase et retourne une action hardware ou RIEN."""
        actions_list = ", ".join(sorted(NATURAL_ACTIONS))
        prompt = (
            f"L'utilisateur dit : \"{phrase}\"\n\n"
            f"Actions disponibles : {actions_list}\n\n"
            "Quelle action correspond à cette phrase ?\n"
            "Réponds avec UNE SEULE action de la liste, rien d'autre.\n"
            "Si aucune action ne correspond, réponds : RIEN"
        )
        result = self._call(
            [{"role": "user", "content": prompt}],
            system_prompt=(
                "Tu es un interpréteur de commandes pour Diablo OS. "
                "Tu reçois une phrase en français et tu retournes "
                "UNIQUEMENT le nom d'une action en majuscules, sans explication."
            ),
            max_tokens=20,
        )
        if result:
            action = result.strip().upper().split()[0]
            if action in NATURAL_ACTIONS:
                return action
        return None

    def understand_app(self, phrase):
        """
        Comprend une phrase et retourne le nom d'une app connue.
        Ex: 'je veux regarder des vidéos' → 'youtube'
        """
        apps_list = ", ".join(sorted(KNOWN_APPS.keys()))
        prompt = (
            f"L'utilisateur dit : \"{phrase}\"\n\n"
            f"Applications disponibles : {apps_list}\n\n"
            "Quelle application l'utilisateur veut-il ouvrir ?\n"
            "Réponds avec UN SEUL nom d'application de la liste, en minuscules.\n"
            "Si aucune application ne correspond, réponds : RIEN"
        )
        result = self._call(
            [{"role": "user", "content": prompt}],
            system_prompt=(
                "Tu es un interpréteur d'intention pour Diablo OS. "
                "Tu identifies quelle application l'utilisateur veut ouvrir. "
                "Réponds UNIQUEMENT avec le nom de l'app en minuscules, sans explication."
            ),
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
            f"État du téléphone de mon Seigneur Aladji :\n"
            f"- Batterie : {niveau}%\n"
            f"- Statut : {statut}\n"
            f"- Température : {temp}°C\n"
            f"- Heure : {heure}\n\n"
            f"Actions disponibles : WIFI_OFF, WIFI_ON, VOL_MUTE, VOL_MAX, VIBRATE, NOTIFY, RIEN\n\n"
            "Réponds UNIQUEMENT au format : ACTION | raison courte"
        )
        return self._call(
            [{"role": "user", "content": prompt}],
            system_prompt=(
                "Tu es Diablo, gardien absolu du téléphone de ton maître Aladji. "
                "Tu gères la batterie avec une précision froide et parfaite. "
                "Réponds UNIQUEMENT au format : ACTION | raison."
            ),
            max_tokens=80,
        )

    def clear_history(self):
        with self._lock:
            self._history = []
        log("Historique effacé")

    def show_history(self):
        with self._lock:
            if not self._history:
                return "Aucun historique de conversation."
            lines = []
            for msg in self._history:
                role   = "Aladji" if msg["role"] == "user" else "Diablo"
                texte  = msg["content"]
                apercu = texte[:100] + ("…" if len(texte) > 100 else "")
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
            log_warn("'requests' absent — update désactivé")
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
║  APPLICATIONS                                ║
║  ouvre youtube          Ouvrir YouTube       ║
║  ouvre whatsapp         Ouvrir WhatsApp      ║
║  ouvre chrome           Ouvrir Chrome        ║
║  ouvre paramètres       Ouvrir Paramètres    ║
║  ouvre caméra           Ouvrir Caméra        ║
║  apps                   Liste des apps       ║
╠══════════════════════════════════════════════╣
║  CONTRÔLE EXACT                              ║
║  lampe on / lampe off   Torche               ║
║  wifi on / wifi off     Wi-Fi                ║
║  son max / silence      Volume               ║
║  vibre                  Vibration            ║
║  photo                  Photo caméra         ║
║  screenshot             Capture d'écran      ║
╠══════════════════════════════════════════════╣
║  LANGAGE NATUREL                             ║
║  hey allume la lampe    Diablo comprend !    ║
║  ouvre moi youtube stp  Langage libre        ║
║  je veux écouter Spotify                     ║
╠══════════════════════════════════════════════╣
║  COMMUNICATION                               ║
║  dit <texte>            Synthèse vocale      ║
║  sms <num> <msg>        Envoyer un SMS       ║
║  notif <msg>            Notification         ║
║  presse-papier          Lire le clipboard    ║
║  localisation           Position GPS         ║
║  batterie               État batterie        ║
╠══════════════════════════════════════════════╣
║  ASSISTANT IA                                ║
║  ask <question>         Poser une question   ║
║  ia reset               Effacer conversation ║
║  ia historique          Voir l'historique    ║
║  batterie ia            Tester l'IA batterie ║
║  tag groq_api_key CLE   Configurer la clé    ║
╠══════════════════════════════════════════════╣
║  MÉMOIRE & APPRENTISSAGE                     ║
║  stats                  Statistiques         ║
║  patterns               Patterns appris      ║
║  alias <nom> <ACTION>   Créer un raccourci   ║
║  tag <clé> [valeur]     Stocker/lire valeur  ║
║  reset patterns         Effacer patterns     ║
║  export                 Export JSON mémoire  ║
╠══════════════════════════════════════════════╣
║  SYSTÈME                                     ║
║  version                Version actuelle     ║
║  update                 Vérifier MAJ         ║
║  aide / help / ?        Cette aide           ║
║  exit / quit            Quitter              ║
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
        """Lance une app par son nom. Retourne True si trouvée."""
        name = name.lower().strip()

        # 1. Correspondance exacte dans KNOWN_APPS
        if name in KNOWN_APPS:
            package = KNOWN_APPS[name]
            print(f"📱 Ouverture de {name}…")
            self.api.open_app(package)
            log(f"App ouverte : {name} ({package})")
            return True

        # 2. Correspondance partielle
        for key, package in KNOWN_APPS.items():
            if name in key or key in name:
                print(f"📱 Ouverture de {key}…")
                self.api.open_app(package)
                log(f"App ouverte : {key} ({package})")
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

        threading.Thread(
            target=self.brain.run, daemon=True, name="Brain"
        ).start()
        threading.Thread(
            target=self.maint.run, daemon=True, name="Maint"
        ).start()

        self._shell()

    def _shell(self):
        while True:
            try:
                raw = input("diablo >>> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            if not raw:
                continue
            try:
                self._dispatch(raw)
            except Exception as e:
                log_err(f"Dispatch error : {e}")

    def _dispatch(self, raw):
        cmd = raw.lower()

        # --- Alias utilisateur ---
        resolved = self.memory.resolve_alias(cmd)
        if resolved:
            log(f"Alias '{cmd}' → {resolved}")
            self.api.execute(resolved)
            self.memory.learn(resolved)
            return

        action = None

        # ---- Commandes exactes ----
        if   cmd == "lampe on":   action = "TORCH_ON"
        elif cmd == "lampe off":  action = "TORCH_OFF"
        elif cmd == "wifi on":    action = "WIFI_ON"
        elif cmd == "wifi off":   action = "WIFI_OFF"
        elif cmd == "son max":    action = "VOL_MAX"
        elif cmd == "silence":    action = "VOL_MUTE"
        elif cmd == "vibre":      action = "VIBRATE"
        elif cmd == "photo":      action = "PHOTO"
        elif cmd == "screenshot": action = "SCREENSHOT"

        # ---- Ouvrir une app ----
        elif cmd.startswith("ouvre "):
            app_name = raw[6:].strip().lower()
            found = self._launch_app(app_name)
            if not found:
                # L'IA essaie de deviner
                if self.memory.get_tag("groq_api_key"):
                    print("🧠 App inconnue, je demande à l'IA…")
                    detected = self.ia.understand_app(app_name)
                    if detected:
                        print(f"✅ Compris : {detected}")
                        self._launch_app(detected)
                    else:
                        print(f"❌ App '{app_name}' introuvable.")
                        print("   Tapez 'apps' pour voir la liste.")
                else:
                    print(f"❌ App '{app_name}' introuvable.")
                    print("   Tapez 'apps' pour voir la liste.")

        # ---- Liste des apps ----
        elif cmd == "apps":
            print("\n📱 Applications disponibles :\n")
            for name in sorted(KNOWN_APPS.keys()):
                print(f"   ouvre {name}")
            print()

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
            content = self.api.clipboard()
            print(f"Presse-papier : {content or '(vide)'}")

        elif cmd == "localisation":
            loc = self.api.location()
            if loc:
                print(f"Position : {loc.get('latitude')}, {loc.get('longitude')}")
            else:
                print("Position indisponible (activer le GPS ?)")

        elif cmd == "batterie":
            bat = self.api.battery()
            if bat:
                print(
                    f"Batterie : {bat.get('percentage', '?')}%  |  "
                    f"État : {bat.get('status', '?')}  |  "
                    f"Temp : {bat.get('temperature', '?')}°C"
                )
            else:
                print("Info batterie indisponible")

        elif cmd == "batterie ia":
            bat = self.api.battery()
            if not bat:
                print("Info batterie indisponible")
                return
            niveau = bat.get("percentage", "?")
            print(f"🔋 Batterie : {niveau}% — analyse en cours…")
            result = self.ia.analyze_battery(bat)
            if result:
                parts     = result.split("|", 1)
                action_ia = parts[0].strip().upper()
                raison    = parts[1].strip() if len(parts) > 1 else ""
                print(f"🤖 IA décide : {action_ia}")
                print(f"   Raison : {raison}")
                confirm = input("Exécuter ? (oui/non) : ").strip().lower()
                if confirm == "oui" and action_ia != "RIEN":
                    if action_ia == "NOTIFY":
                        self.api.execute("NOTIFY", raison)
                    else:
                        self.api.execute(action_ia)
                    print("✅ Action exécutée.")
                else:
                    print("Annulé.")
            else:
                print("L'IA n'a pas pu analyser.")

        elif cmd.startswith("ask "):
            question = raw[4:].strip()
            if question:
                answer = self.ia.ask(question)
                print(f"\n😈 Diablo : {answer}\n")
            else:
                print("Usage : ask <ta question>")

        elif cmd == "ia reset":
            self.ia.clear_history()
            print("Historique effacé.")

        elif cmd == "ia historique":
            print(self.ia.show_history())

        elif cmd == "ia":
            print("Commandes IA :")
            print("  ask <question>    Poser une question")
            print("  ia reset          Effacer l'historique")
            print("  ia historique     Voir la conversation")
            print("  batterie ia       Tester l'IA batterie")
            print("  tag groq_api_key  Configurer la clé")

        elif cmd == "stats":
            print(json.dumps(self.memory.data["stats"], indent=2, ensure_ascii=False))

        elif cmd == "patterns":
            p = self.memory.data.get("patterns", {})
            if p:
                print(json.dumps(p, indent=2, ensure_ascii=False))
            else:
                print("Aucun pattern enregistré")

        elif cmd == "reset patterns":
            confirm = input("Confirmer reset ? (oui/non) : ").strip().lower()
            if confirm == "oui":
                self.memory.reset_patterns()
            else:
                print("Annulé")

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
                val = self.memory.get_tag(parts[1])
                print(f"Tag '{parts[1]}' = {val!r}")
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

                # 1. L'IA essaie de deviner une app
                app = self.ia.understand_app(raw)
                if app:
                    print(f"📱 Compris : ouvrir {app}")
                    self._launch_app(app)
                    return

                # 2. L'IA essaie de deviner une action hardware
                detected = self.ia.understand_command(raw)
                if detected and detected != "RIEN":
                    print(f"✅ Compris : {detected}")
                    self.api.execute(detected)
                    self.memory.learn(detected)
                    log(f"Langage naturel : '{raw}' → {detected}")
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
