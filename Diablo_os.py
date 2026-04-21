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
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# =========================
# CONFIG
# =========================
VERSION = "5.0.0"
BASE_DIR = Path(__file__).parent
MEMORY_FILE = BASE_DIR / "diablo_memory.json"
BACKUP_FILE = BASE_DIR / "diablo_memory.bak.json"
LOG_FILE = BASE_DIR / "diablo.log"
UPDATE_URL = "https://raw.githubusercontent.com/diallo65377-lgtm/Diablo/main/Diablo_os.py"
UPDATE_INTERVAL = 3600          # vérif update toutes les heures (au lieu de 30min)
BRAIN_INTERVAL = 30             # cerveau tourne toutes les 30s (au lieu de 60s)
DEBOUNCE_DELAY = 300            # 5 min entre deux exécutions auto d'une même action
MIN_PATTERN_COUNT = 3           # seuil pour déclencher une prédiction
LOW_BATTERY_THRESHOLD = 15
CRITICAL_BATTERY_THRESHOLD = 5

# =========================
# LOGGING STRUCTURÉ
# =========================
def setup_logging():
    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S"
    )
    logger = logging.getLogger("diablo")
    logger.setLevel(logging.DEBUG)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Fichier (rotation manuelle simple : max 500 Ko)
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 500_000:
            LOG_FILE.rename(LOG_FILE.with_suffix(".bak.log"))
        fh = logging.FileHandler(LOG_FILE)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    return logger

logger = setup_logging()
log = logger.info
log_warn = logger.warning
log_err = logger.error
log_dbg = logger.debug

# =========================
# MÉMOIRE ROBUSTE
# =========================
class NeuralMemory:
    """
    Mémoire persistante avec sauvegarde atomique et backup.
    Nouvelle structure v5 : ajout session_count, version, tags libres.
    """

    SCHEMA_VERSION = 2

    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()

    # --- Schéma par défaut ---
    def _default(self) -> dict:
        return {
            "_schema": self.SCHEMA_VERSION,
            "patterns": {},          # {hour: {action: count}}
            "aliases": {},           # {alias: action}
            "tags": {},              # {key: value} — données libres
            "stats": {
                "actions": 0,
                "sessions": 0,
                "created_at": datetime.now().isoformat(),
                "last_seen": None,
            },
        }

    # --- Validation + migration ---
    def _validate(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        return all(k in data for k in ("patterns", "stats"))

    def _migrate(self, data: dict) -> dict:
        """Migre les anciennes structures vers la v5."""
        if "_schema" not in data:
            data.setdefault("aliases", {})
            data.setdefault("tags", {})
            data.setdefault("_schema", self.SCHEMA_VERSION)
            data["stats"].setdefault("sessions", 0)
            data["stats"].setdefault("created_at", datetime.now().isoformat())
            data["stats"].setdefault("last_seen", None)
            log("Mémoire migrée vers schema v2")
        return data

    # --- Chargement ---
    def _load_file(self, path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load(self) -> dict:
        for label, path in [("principale", MEMORY_FILE), ("backup", BACKUP_FILE)]:
            data = self._load_file(path)
            if self._validate(data):
                log(f"Mémoire chargée ({label})")
                return self._migrate(data)
            if data is not None:
                log_warn(f"Mémoire {label} corrompue, ignorée")
        log("Reset mémoire")
        return self._default()

    # --- Sauvegarde atomique ---
    def _atomic_save(self, data: dict):
        tmp = MEMORY_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            if MEMORY_FILE.exists():
                MEMORY_FILE.replace(BACKUP_FILE)
            tmp.replace(MEMORY_FILE)
        except Exception as e:
            log_err(f"Sauvegarde échouée : {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def save(self):
        with self._lock:
            self.data["stats"]["last_seen"] = datetime.now().isoformat()
            self._atomic_save(self.data)

    # --- API publique ---
    def learn(self, action: str):
        hour = str(datetime.now().hour)
        with self._lock:
            self.data["patterns"].setdefault(hour, {})
            self.data["patterns"][hour][action] = \
                self.data["patterns"][hour].get(action, 0) + 1
            self.data["stats"]["actions"] += 1
        self.save()

    def predict(self) -> Optional[str]:
        patterns = self.data.get("patterns", {})
        hour = str(datetime.now().hour)
        actions = patterns.get(hour, {})
        if not actions:
            return None
        best = max(actions, key=actions.get)
        return best if actions[best] >= MIN_PATTERN_COUNT else None

    def add_alias(self, alias: str, action: str):
        with self._lock:
            self.data["aliases"][alias.lower()] = action.upper()
        self.save()
        log(f"Alias ajouté : '{alias}' → {action.upper()}")

    def resolve_alias(self, cmd: str) -> Optional[str]:
        return self.data.get("aliases", {}).get(cmd.lower())

    def set_tag(self, key: str, value):
        with self._lock:
            self.data["tags"][key] = value
        self.save()

    def get_tag(self, key: str, default=None):
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

    def export_json(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)

# =========================
# TERMUX API
# =========================
ACTIONS: dict[str, list[str]] = {
    "TORCH_ON":  ["termux-torch", "on"],
    "TORCH_OFF": ["termux-torch", "off"],
    "WIFI_ON":   ["termux-wifi-enable", "true"],
    "WIFI_OFF":  ["termux-wifi-enable", "false"],
    "VIBRATE":   ["termux-vibrate", "-d", "500"],
    "VOL_MAX":   ["termux-volume", "music", "15"],
    "VOL_MUTE":  ["termux-volume", "music", "0"],
    "PHOTO":     ["termux-camera-photo", "-c", "0",
                  f"/sdcard/photo_{int(time.time())}.jpg"],
    "SCREENSHOT":["termux-screenshot",
                  f"/sdcard/screen_{int(time.time())}.png"],
    "CLIPBOARD": ["termux-clipboard-get"],     # lecture presse-papier
    "LOCATION":  ["termux-location"],          # récupère GPS
}

class TermuxAPI:
    def _run(self, cmd: list[str], capture=False) -> Optional[str]:
        try:
            if capture:
                out = subprocess.check_output(cmd, timeout=5, stderr=subprocess.DEVNULL)
                return out.decode().strip()
            else:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log_warn(f"Commande introuvable : {cmd[0]}")
        except subprocess.TimeoutExpired:
            log_warn(f"Timeout : {cmd[0]}")
        except Exception as e:
            log_err(f"Erreur commande {cmd[0]} : {e}")
        return None

    def execute(self, action: str, param: Optional[str] = None):
        action = action.upper()

        if action == "SAY" and param:
            self._run(["termux-tts-speak", param])
            return True

        if action == "OPEN" and param:
            self._run(["termux-open", param])
            return True

        if action == "NOTIFY" and param:
            self._run(["termux-notification", "--title", "Diablo OS", "--content", param])
            return True

        cmd = ACTIONS.get(action)
        if cmd:
            # PHOTO : mettre à jour le timestamp à chaque appel
            if action == "PHOTO":
                cmd = ["termux-camera-photo", "-c", "0",
                       f"/sdcard/photo_{int(time.time())}.jpg"]
            elif action == "SCREENSHOT":
                cmd = ["termux-screenshot",
                       f"/sdcard/screen_{int(time.time())}.png"]
            self._run(cmd)
            return True

        log_warn(f"Action inconnue : {action}")
        return False

    def send_sms(self, number: str, message: str):
        if not number.lstrip("+").isdigit():
            log_warn("Numéro SMS invalide")
            return
        self._run(["termux-sms-send", "-n", number, message])
        log(f"SMS envoyé à {number}")

    def battery(self) -> dict:
        raw = self._run(["termux-battery-status"], capture=True)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return {}

    def clipboard(self) -> Optional[str]:
        return self._run(["termux-clipboard-get"], capture=True)

    def location(self) -> Optional[dict]:
        raw = self._run(["termux-location"], capture=True)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return None

    def contacts(self) -> list:
        raw = self._run(["termux-contact-list"], capture=True)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return []

# =========================
# CERVEAU EXÉCUTIF
# =========================
class ExecutiveBrain:
    def __init__(self, api: TermuxAPI, memory: NeuralMemory):
        self.api = api
        self.memory = memory
        self._running = True
        self._last_action: dict[str, float] = {}
        self._stop_event = threading.Event()

    def stop(self):
        self._running = False
        self._stop_event.set()

    def _debounced(self, action: str) -> bool:
        now = time.time()
        last = self._last_action.get(action, 0)
        if now - last > DEBOUNCE_DELAY:
            self._last_action[action] = now
            return True
        return False

    def run(self):
        log("Cerveau exécutif démarré")
        while self._running:
            try:
                self._tick()
            except Exception as e:
                log_err(f"Erreur brain : {e}")
            self._stop_event.wait(timeout=BRAIN_INTERVAL)

    def _tick(self):
        bat = self.api.battery()
        level = bat.get("percentage", 100)
        status = bat.get("status", "")
        charging = status.upper() == "CHARGING"

        # Batterie critique → wifi off + notification
        if level <= CRITICAL_BATTERY_THRESHOLD and not charging:
            if self._debounced("_CRITICAL_BAT"):
                self.api.execute("WIFI_OFF")
                self.api.execute("NOTIFY", f"Batterie critique : {level}%")
                log_warn(f"Batterie critique ({level}%) — wifi coupé")

        elif level <= LOW_BATTERY_THRESHOLD and not charging:
            if self._debounced("_LOW_BAT"):
                self.api.execute("WIFI_OFF")
                log_warn(f"Batterie faible ({level}%) — wifi coupé")

        # Prédiction comportementale
        action = self.memory.predict()
        if action and self._debounced(action):
            log(f"Auto-action prédite : {action}")
            self.api.execute(action)

# =========================
# MISE À JOUR AUTOMATIQUE
# =========================
class MaintenanceBrain:
    def __init__(self):
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def check_update(self):
        if not REQUESTS_AVAILABLE:
            log_warn("Module 'requests' absent — mise à jour désactivée")
            return

        try:
            r = requests.get(UPDATE_URL, timeout=10)
            r.raise_for_status()
        except Exception as e:
            log_warn(f"Échec récupération update : {e}")
            return

        new_code = r.text

        # Vérifications de sécurité minimales
        if "class DiabloOS" not in new_code:
            log_warn("Update rejeté : signature manquante")
            return

        current_code = Path(__file__).read_text(encoding="utf-8")
        if self._sha256(new_code) == self._sha256(current_code):
            log_dbg("Déjà à jour")
            return

        if f'VERSION = "{VERSION}"' in new_code:
            log_dbg("Même version, pas de mise à jour")
            return

        log("Nouvelle version détectée — mise à jour…")
        backup = Path(__file__).with_suffix(".bak.py")
        try:
            Path(__file__).replace(backup)
            Path(__file__).write_text(new_code, encoding="utf-8")
            log("Redémarrage après mise à jour…")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            log_err(f"Erreur écriture update : {e}")
            # Restaurer depuis backup
            if backup.exists():
                backup.replace(Path(__file__))

    def run(self):
        log("Maintenance brain démarré")
        while not self._stop_event.is_set():
            self.check_update()
            self._stop_event.wait(timeout=UPDATE_INTERVAL)

# =========================
# SHELL — AIDE INTÉGRÉE
# =========================
HELP_TEXT = """
╔══════════════════════════════════════════════╗
║           DIABLO OS v{ver} — AIDE              ║
╠══════════════════════════════════════════════╣
║  CONTRÔLE                                    ║
║  lampe on/off     Torche                     ║
║  wifi on/off      Wi-Fi                      ║
║  son max          Volume max                 ║
║  silence          Volume 0                   ║
║  vibre            Vibration                  ║
║  photo            Photo caméra front         ║
║  screenshot       Capture d'écran            ║
║                                              ║
║  COMMUNICATION                               ║
║  dit <texte>      Synthèse vocale            ║
║  sms <num> <msg>  Envoyer SMS                ║
║  notif <msg>      Notification système       ║
║  ouvre <url/app>  Ouvrir une ressource       ║
║  presse-papier    Lire le presse-papier      ║
║  localisation     Position GPS               ║
║                                              ║
║  MÉMOIRE                                     ║
║  stats            Statistiques               ║
║  patterns         Afficher les patterns      ║
║  alias <a> <act>  Créer un alias             ║
║  tag <k> <v>      Stocker une valeur         ║
║  tag <k>          Lire une valeur            ║
║  reset patterns   Effacer les patterns       ║
║  export           Exporter la mémoire (JSON) ║
║                                              ║
║  SYSTÈME                                     ║
║  batterie         État batterie              ║
║  update           Vérifier mise à jour       ║
║  version          Afficher la version        ║
║  aide / help      Cette aide                 ║
║  exit / quit      Quitter                    ║
╚══════════════════════════════════════════════╝
""".format(ver=VERSION)

# =========================
# OS PRINCIPAL
# =========================
class DiabloOS:
    def __init__(self):
        self.api = TermuxAPI()
        self.memory = NeuralMemory()
        self.brain = ExecutiveBrain(self.api, self.memory)
        self.maint = MaintenanceBrain()
        self._setup_signals()

    def _setup_signals(self):
        """Arrêt propre sur SIGINT / SIGTERM."""
        def handler(sig, frame):
            print("\n[Arrêt propre…]")
            self.brain.stop()
            self.maint.stop()
            self.memory.save()
            sys.exit(0)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def start(self):
        os.system("clear")
        print(f"""
  ██████╗ ██╗ █████╗ ██████╗ ██╗      ██████╗
  ██╔══██╗██║██╔══██╗██╔══██╗██║     ██╔═══██╗
  ██║  ██║██║███████║██████╔╝██║     ██║   ██║
  ██║  ██║██║██╔══██║██╔══██╗██║     ██║   ██║
  ██████╔╝██║██║  ██║██████╔╝███████╗╚██████╔╝
  ╚═════╝ ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝ ╚═════╝
             OS v{VERSION}  — Tapez 'aide' pour l'aide
""")

        self.memory.increment_session()

        threading.Thread(target=self.brain.run, daemon=True, name="Brain").start()
        threading.Thread(target=self.maint.run, daemon=True, name="Maint").start()

        self.shell()

    # ------------------------------------------------------------------
    # SHELL
    # ------------------------------------------------------------------
    def shell(self):
        while True:
            try:
                raw = input("diablo >>> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not raw:
                continue

            cmd = raw.lower()
            self._dispatch(cmd, raw)

    def _dispatch(self, cmd: str, raw: str):
        # --- Alias utilisateur ---
        resolved = self.memory.resolve_alias(cmd)
        if resolved:
            log(f"Alias '{cmd}' → {resolved}")
            self.api.execute(resolved)
            self.memory.learn(resolved)
            return

        # --- Commandes intégrées ---
        action: Optional[str] = None

        # Torche
        if cmd == "lampe on":
            action = "TORCH_ON"
        elif cmd == "lampe off":
            action = "TORCH_OFF"

        # Wi-Fi
        elif cmd == "wifi on":
            action = "WIFI_ON"
        elif cmd == "wifi off":
            action = "WIFI_OFF"

        # Audio
        elif cmd == "son max":
            action = "VOL_MAX"
        elif cmd == "silence":
            action = "VOL_MUTE"

        # Divers
        elif cmd == "vibre":
            action = "VIBRATE"
        elif cmd == "photo":
            action = "PHOTO"
        elif cmd == "screenshot":
            action = "SCREENSHOT"

        # TTS
        elif cmd.startswith("dit "):
            text = raw[4:].strip()
            if text:
                self.api.execute("SAY", text)
            else:
                print("Usage : dit <texte>")

        # Notification
        elif cmd.startswith("notif "):
            msg = raw[6:].strip()
            self.api.execute("NOTIFY", msg)

        # Ouvrir ressource
        elif cmd.startswith("ouvre "):
            target = raw[6:].strip()
            self.api.execute("OPEN", target)

        # SMS
        elif cmd.startswith("sms "):
            parts = raw.split(maxsplit=2)
            if len(parts) == 3:
                _, number, message = parts
                self.api.send_sms(number, message)
            else:
                print("Usage : sms <numéro> <message>")

        # Presse-papier
        elif cmd == "presse-papier":
            content = self.api.clipboard()
            print(f"Presse-papier : {content or '(vide)'}")

        # GPS
        elif cmd == "localisation":
            loc = self.api.location()
            if loc:
                lat = loc.get("latitude", "?")
                lon = loc.get("longitude", "?")
                print(f"Position : {lat}, {lon}")
            else:
                print("Position indisponible")

        # Batterie
        elif cmd == "batterie":
            bat = self.api.battery()
      
