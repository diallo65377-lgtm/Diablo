import os
import sys
import json
import time
import threading
import subprocess
import requests
from datetime import datetime

# =========================
# CONFIG
# =========================
VERSION = "4.1.0"
MEMORY_FILE = "diablo_memory.json"
BACKUP_FILE = "diablo_memory.bak.json"
UPDATE_URL = "https://raw.githubusercontent.com/diallo65377-lgtm/Diablo/main/Diablo_os.py"

# =========================
# LOG
# =========================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# =========================
# MÉMOIRE ROBUSTE
# =========================
class NeuralMemory:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self.load()

    def default(self):
        return {
            "patterns": {},
            "stats": {"actions": 0}
        }

    def validate(self, data):
        if not isinstance(data, dict):
            return False
        if "patterns" not in data:
            return False
        if "stats" not in data:
            return False
        return True

    def load_file(self, path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return None

    def load(self):
        # 1. Charger mémoire principale
        data = self.load_file(MEMORY_FILE)

        if self.validate(data):
            return data

        log("Mémoire principale corrompue, tentative backup...")

        # 2. Charger backup
        backup = self.load_file(BACKUP_FILE)

        if self.validate(backup):
            log("Backup chargé avec succès")
            return backup

        log("Aucune mémoire valide, reset")
        return self.default()

    def atomic_save(self, data):
        temp_file = MEMORY_FILE + ".tmp"

        try:
            # écrire fichier temporaire
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)

            # sauvegarde backup
            if os.path.exists(MEMORY_FILE):
                os.replace(MEMORY_FILE, BACKUP_FILE)

            # remplacement atomique
            os.replace(temp_file, MEMORY_FILE)

        except Exception as e:
            log(f"Erreur sauvegarde: {e}")

    def save(self):
        with self.lock:
            self.atomic_save(self.data)

    def learn(self, action):
        hour = str(datetime.now().hour)

        with self.lock:
            self.data["patterns"].setdefault(hour, {})
            self.data["patterns"][hour][action] = self.data["patterns"][hour].get(action, 0) + 1
            self.data["stats"]["actions"] += 1

        self.save()

    def predict(self):
        patterns = self.data.get("patterns", {})
        hour = str(datetime.now().hour)

        if hour not in patterns:
            return None

        actions = patterns[hour]
        if not actions:
            return None

        best = max(actions, key=actions.get)

        if actions[best] >= 3:
            return best

        return None

# =========================
# TERMUX API
# =========================
class TermuxAPI:
    def run(self, cmd):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log(f"Erreur commande: {e}")

    def execute(self, action, param=None):
        cmds = {
            "TORCH_ON": ["termux-torch", "on"],
            "TORCH_OFF": ["termux-torch", "off"],
            "WIFI_ON": ["termux-wifi-enable", "true"],
            "WIFI_OFF": ["termux-wifi-enable", "false"],
            "VIBRATE": ["termux-vibrate", "-d", "500"],
            "VOL_MAX": ["termux-volume", "music", "15"],
            "VOL_MUTE": ["termux-volume", "music", "0"],
            "PHOTO": ["termux-camera-photo", "-c", "0", f"/sdcard/photo_{int(time.time())}.jpg"],
        }

        if action == "SAY" and param:
            self.run(["termux-tts-speak", param])
            return

        if action in cmds:
            self.run(cmds[action])

    def send_sms(self, number, message):
        self.run(["termux-sms-send", "-n", number, message])

    def battery(self):
        try:
            out = subprocess.check_output(["termux-battery-status"], timeout=2)
            return json.loads(out)
        except:
            return {}

# =========================
# CERVEAU
# =========================
class ExecutiveBrain:
    def __init__(self, api, memory):
        self.api = api
        self.memory = memory
        self.running = True
        self.last_action = {}

    def run(self):
        while self.running:
            try:
                bat = self.api.battery()
                level = bat.get("percentage", 100)
                charging = bat.get("status") == "CHARGING"

                if level < 15 and not charging:
                    self.api.execute("WIFI_OFF")

                action = self.memory.predict()

                if action:
                    now = time.time()
                    if action not in self.last_action or now - self.last_action[action] > 300:
                        log(f"Auto-action: {action}")
                        self.api.execute(action)
                        self.last_action[action] = now

            except Exception as e:
                log(f"Erreur brain: {e}")

            time.sleep(60)

# =========================
# UPDATE
# =========================
class MaintenanceBrain:
    def check_update(self):
        try:
            r = requests.get(UPDATE_URL, timeout=10)
            if r.status_code != 200:
                return

            new_code = r.text

            if "class DiabloOS" not in new_code:
                log("Update rejeté")
                return

            if f'VERSION = "{VERSION}"' in new_code:
                return

            log("Nouvelle version détectée")

            backup = __file__ + ".bak"
            os.rename(__file__, backup)

            with open(__file__, "w") as f:
                f.write(new_code)

            log("Redémarrage")
            os.execv(sys.executable, ['python'] + sys.argv)

        except Exception as e:
            log(f"Update error: {e}")

    def run(self):
        while True:
            self.check_update()
            time.sleep(1800)

# =========================
# OS
# =========================
class DiabloOS:
    def __init__(self):
        self.api = TermuxAPI()
        self.memory = NeuralMemory()
        self.brain = ExecutiveBrain(self.api, self.memory)
        self.maint = MaintenanceBrain()

    def start(self):
        os.system("clear")
        print(f"=== DIABLO OS v{VERSION} ===")

        threading.Thread(target=self.brain.run, daemon=True).start()
        threading.Thread(target=self.maint.run, daemon=True).start()

        self.shell()

    def shell(self):
        while True:
            try:
                cmd = input(">>> ").strip().lower()
                if not cmd:
                    continue

                if cmd in ["exit", "quit"]:
                    break

                action = None

                if cmd == "lampe on":
                    action = "TORCH_ON"

                elif cmd == "lampe off":
                    action = "TORCH_OFF"

                elif cmd == "wifi on":
                    action = "WIFI_ON"

                elif cmd == "wifi off":
                    action = "WIFI_OFF"

                elif cmd == "vibre":
                    action = "VIBRATE"

                elif cmd == "photo":
                    action = "PHOTO"

                elif cmd == "son max":
                    action = "VOL_MAX"

                elif cmd == "silence":
                    action = "VOL_MUTE"

                elif cmd.startswith("dit "):
                    text = cmd[4:]
                    self.api.execute("SAY", text)

                elif cmd.startswith("sms "):
                    parts = cmd.split()
                    if len(parts) >= 3:
                        number = parts[1]
                        message = " ".join(parts[2:])
                        self.api.send_sms(number, message)
                        log(f"SMS envoyé à {number}")

                elif cmd == "stats":
                    print(self.memory.data["stats"])

                elif cmd == "update":
                    self.maint.check_update()

                if action:
                    self.api.execute(action)
                    self.memory.learn(action)
                    log(f"Action: {action}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"Erreur: {e}")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    DiabloOS().start()
