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
VERSION = "5.4.0"
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

# Groq API (gratuit et rapide)
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MAX_TOKENS = 512
GROQ_HISTORY_MAX = 10

# IA Batterie
BATTERY_AI_THRESHOLD = 20      # L'IA intervient seulement sous 20%
BATTERY_AI_INTERVAL  = 300     # Toutes les 5 minutes (en secondes)

# =========================
# LOGGING — ne plante jamais
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

logger = setup_logging()
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
        # On n'enregistre pas les actions IA dans les patterns
        if action in ("ASK_IA", "BATTERY_AI"):
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
# ASSISTANT IA (GROQ — GRATUIT)
# =========================
class GroqAssistant:
    """
    Assistant IA utilisant Groq (gratuit et très rapide).
    Garde un historique de la conversation.
    """

    SYSTEM_PROMPT = (
        "Tu es Diablo, un assistant IA intégré dans Diablo OS, "
        "un système qui tourne sur Android via Termux. "
        "Tu es utile, concis et tu parles toujours en français. "
        "Tu peux aider avec des questions générales, "
        "de la programmation Python, ou l'utilisation d'Android."
    )

    def __init__(self, memory):
        self.memory = memory
        self._history = []
        self._lock = threading.Lock()

    def _get_api_key(self):
        return self.memory.get_tag("groq_api_key")

    def _call(self, messages, system_prompt=None, max_tokens=None):
        """Appel brut à l'API Groq. Retourne le texte ou None."""
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
        """Question interactive avec historique."""
        if not REQUESTS_AVAILABLE:
            return "Erreur : installe 'requests' avec : pip install requests"

        if not self._get_api_key():
            return (
                "Clé API Groq manquante !\n"
                "1. Va sur https://console.groq.com\n"
                "2. Crée un compte gratuit\n"
                "3. Va dans API Keys > Create API Key\n"
                "4. Configure-la avec :\n"
                "   tag groq_api_key gsk_XXXXXXXX"
            )

        with self._lock:
            self._history.append({"role": "user", "content": question})
            if len(self._history) > GROQ_HISTORY_MAX * 2:
                self._history = self._history[-(GROQ_HISTORY_MAX * 2):]
            messages = list(self._history)

        print("⚡ Groq réfléchit…", flush=True)

        try:
            api_key = self._get_api_key()
            response = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "max_tokens": GROQ_MAX_TOKENS,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        *messages,
                    ],
                },
                timeout=30,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]

            with self._lock:
                self._history.append({"role": "assistant", "content": answer})

            return answer

        except requests.exceptions.ConnectionError:
            return "Erreur : pas de connexion internet. Active le Wi-Fi."
        except requests.exceptions.Timeout:
            return "Erreur : pas de réponse (timeout 30s). Réessaie."
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status == 401:
                return "Erreur : clé API invalide. Vérifie avec : tag groq_api_key"
            elif status == 429:
                return "Erreur : trop de requêtes. Attends quelques secondes."
            return f"Erreur HTTP {status} : {e}"
        except Exception as e:
            log_err(f"Groq error : {e}")
            return f"Erreur inattendue : {e}"

    def analyze_battery(self, bat):
        """
        Analyse la batterie et retourne UNE action à exécuter,
        ou 'RIEN' si tout va bien.
        """
        heure = datetime.now().strftime("%H:%M")
        niveau = bat.get("percentage", "?")
        statut = bat.get("status", "?")
        temp   = bat.get("temperature", "?")

        prompt = f"""Tu es le cerveau de Diablo OS sur Android.
État actuel du téléphone :
- Batterie : {niveau}%
- Statut : {statut}
- Température : {temp}°C
- Heure : {heure}

Actions disponibles : WIFI_OFF, WIFI_ON, VOL_MUTE, VOL_MAX, VIBRATE, NOTIFY, RIEN

Réponds avec UNE SEULE action parmi la liste ci-dessus, puis explique pourquoi en une phrase courte.
Format exact : ACTION | raison
Exemple : WIFI_OFF | Batterie critique, économiser l'énergie."""

        result = self._call(
            [{"role": "user", "content": prompt}],
            system_prompt="Tu es un système autonome de gestion de batterie Android. Réponds uniquement au format demandé.",
            max_tokens=80,
        )
        return result

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
                role = "Toi" if msg["role"] == "user" else "Diablo"
                texte = msg["content"]
                apercu = texte[:100] + ("…" if len(texte) > 100 else "")
                lines.append(f"[{role}] {apercu}")
            return "\n".join(lines)


# =========================
# CERVEAU EXÉCUTIF
# =========================
class ExecutiveBrain:
    def __init__(self, api, memory, ia):
        self.api    = api
        self.memory = memory
        self.ia     = ia
        self._running  = True
        self._last     = {}
        self._stop     = threading.Event()
        self._last_battery_ai = 0  # timestamp dernier appel IA batterie

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
        bat     = self.api.battery()
        level   = bat.get("percentage", 100)
        charging = bat.get("status", "").upper() == "CHARGING"

        # --- Règles fixes d'urgence (toujours actives) ---
        if level <= CRITICAL_BATTERY_THRESHOLD and not charging:
            if self._debounce("_crit"):
                self.api.execute("WIFI_OFF")
                self.api.execute("NOTIFY", f"Batterie critique {level}%!")
                log_warn(f"Batterie critique : {level}%")

        # --- IA Batterie (seulement < 20% et toutes les 5 min) ---
        now = time.time()
        if (level <= BATTERY_AI_THRESHOLD
                and not charging
                and now - self._last_battery_ai >= BATTERY_AI_INTERVAL):

            self._last_battery_ai = now
            log(f"IA batterie activée ({level}%)")

            result = self.ia.analyze_battery(bat)
            if result:
                # Parser la réponse : "ACTION | raison"
                parts = result.split("|", 1)
                action = parts[0].strip().upper()
                raison = parts[1].strip() if len(parts) > 1 else ""

                log(f"IA décision : {action} — {raison}")

                if action == "RIEN":
                    log("IA : aucune action nécessaire")
                elif action == "NOTIFY":
                    self.api.execute("NOTIFY", raison or f"Batterie {level}%")
                elif action in ("WIFI_OFF", "WIFI_ON", "VOL_MUTE",
                                "VOL_MAX", "VIBRATE"):
                    self.api.execute(action)
                    self.api.execute(
                        "NOTIFY",
                        f"IA: {action} — {raison}"
                    )
                else:
                    log_warn(f"IA réponse invalide : {action}")

        # --- Patterns appris ---
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
