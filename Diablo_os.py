import os
import sys
import json
import time
import threading
import subprocess
import random
import requests
from datetime import datetime

# =========================
# CONFIGURATION GLOBALE
# =========================
VERSION = "3.5.0"
MEMORY_FILE = "diablo_neural_memory.json"
UPDATE_URL = "https://raw.githubusercontent.com/diallo65377-lgtm/Diablo/main/diablo_os.py"

# =========================
# SYSTÈME NERVEUX (MÉMOIRE)
# =========================
class NeuralMemory:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self.load()

    def load(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    return json.load(f)
            except: return self.default_state()
        return self.default_state()

    def default_state(self):
        return {
            "patterns": {},
            "stats": {"actions": 0, "updates": 0},
            "contacts": {}, # Stockage de numéros pour SMS
            "last_reboot": str(datetime.now())
        }

    def save(self):
        with self.lock:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.data, f, indent=2)

    def learn(self, action):
        hour = str(datetime.now().hour)
        with self.lock:
            if hour not in self.data["patterns"]:
                self.data["patterns"][hour] = {}
            self.data["patterns"][hour][action] = self.data["patterns"][hour].get(action, 0) + 1
            self.data["stats"]["actions"] += 1
        self.save()

    def get_prediction(self):
        hour = str(datetime.now().hour)
        patterns = self.data["patterns"].get(hour, {})
        if not patterns: return None
        best_action = max(patterns, key=patterns.get)
        if patterns[best_action] >= 3: # Seuil d'apprentissage réduit pour plus de réactivité
            return best_action
        return None

# =========================
# INTERFACE TERMUX API PRO
# =========================
class TermuxAPI:
    def execute(self, action, params=None):
        cmds = {
            "TORCH_ON": ["termux-torch", "on"],
            "TORCH_OFF": ["termux-torch", "off"],
            "BRIGHT_LOW": ["termux-brightness", "10"],
            "BRIGHT_HIGH": ["termux-brightness", "255"],
            "VIBRATE": ["termux-vibrate", "-d", "500"],
            "WIFI_ON": ["termux-wifi-enable", "true"],
            "WIFI_OFF": ["termux-wifi-enable", "false"],
            "VOL_MUTE": ["termux-volume", "music", "0"],
            "VOL_MAX": ["termux-volume", "music", "15"],
            "PHOTO": ["termux-camera-photo", "-c", "0", f"/sdcard/diablo_{int(time.time())}.jpg"],
            "SAY": ["termux-tts-speak"]
        }
        
        if action in cmds:
            full_cmd = cmds[action]
            if action == "SAY" and params:
                full_cmd.append(params)
            subprocess.Popen(full_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def send_sms(self, number, message):
        subprocess.Popen(["termux-sms-send", "-n", number, message])

    def get_battery(self):
        try: return json.loads(subprocess.check_output(["termux-battery-status"], timeout=2))
        except: return {}

# =========================
# LES TROIS CERVEAUX
# =========================
class ExecutiveBrain:
    """Cerveau A : Prend des décisions basées sur l'état et l'apprentissage."""
    def __init__(self, api, memory):
        self.api, self.memory = api, memory
        self.is_running = True

    def run(self):
        while self.is_running:
            try:
                # 1. Gestion automatique de l'énergie
                bat = self.api.get_battery()
                level = bat.get("percentage", 100)
                is_charging = bat.get("status") == "CHARGING"

                if level < 15 and not is_charging:
                    self.api.execute("BRIGHT_LOW")
                    self.api.execute("WIFI_OFF")
                
                # 2. Exécution des habitudes apprises
                prediction = self.memory.get_prediction()
                if prediction:
                    self.api.execute(prediction)
                    
            except Exception as e: pass
            time.sleep(60)

class SupervisorBrain:
    """Cerveau B : Surveille les erreurs et la santé du système."""
    def __init__(self, b_a, b_c):
        self.b_a, self.b_c = b_a, b_c

    def run(self):
        while True:
            if not self.b_a.is_running:
                self.b_a.is_running = True # Relance automatique
            time.sleep(30)

class MaintenanceBrain:
    """Cerveau C : Gère les mises à jour et l'évolution du code."""
    def __init__(self):
        pass

    def check_update(self):
        try:
            r = requests.get(UPDATE_URL, timeout=10)
            if r.status_code == 200:
                if f'VERSION = "{VERSION}"' not in r.text:
                    print(f"\n[Maintenance] Mise à jour vers une nouvelle version...")
                    with open(__file__, "w") as f:
                        f.write(r.text)
                    os.execv(sys.executable, ['python'] + sys.argv)
        except: pass

    def run(self):
        while True:
            self.check_update()
            time.sleep(1800)

# =========================
# NOYAU CENTRAL
# =========================
class DiabloOS:
    def __init__(self):
        self.api = TermuxAPI()
        self.memory = NeuralMemory()
        self.brain_a = ExecutiveBrain(self.api, self.memory)
        self.brain_c = MaintenanceBrain()
        self.brain_b = SupervisorBrain(self.brain_a, self.brain_c)

    def start(self):
        os.system("clear")
        print(f"====================================")
        print(f"      DIABLO NEURAL OS v{VERSION}")
        print(f"====================================")
        print(f"[*] Apprentissage : ACTIF")
        print(f"[*] Surveillance  : DOUBLE CERVEAU")
        print(f"[*] Update URL    : {UPDATE_URL}")
        print(f"------------------------------------")

        for thread in [self.brain_a.run, self.brain_b.run, self.brain_c.run]:
            threading.Thread(target=thread, daemon=True).start()

        self.shell()

    def shell(self):
        while True:
            try:
                cmd = input(f"Diablo@{VERSION} # ").lower().strip()
                if not cmd: continue
                if cmd in ["exit", "quit"]: break
                
                # --- SYSTÈME DE COMMANDES ÉVOLUÉ ---
                action = None
                
                # Gestion Lumière
                if "lampe on" in cmd: action = "TORCH_ON"
                elif "lampe off" in cmd: action = "TORCH_OFF"
                
                # Gestion Média / Audio
                elif "chut" in cmd or "silence" in cmd:
                    self.api.execute("VOL_MUTE")
                    self.api.execute("VIBRATE")
                    print("| Diablo |: Mode silencieux activé.")
                elif "son max" in cmd: action = "VOL_MAX"
                elif "dit" in cmd:
                    text = cmd.replace("dit", "").strip()
                    self.api.execute("SAY", text)
                
                # Gestion Réseau
                elif "wifi on" in cmd: action = "WIFI_ON"
                elif "wifi off" in cmd: action = "WIFI_OFF"
                
                # Gestion Capteurs
                elif "photo" in cmd: action = "PHOTO"
                elif "vibre" in cmd: action = "VIBRATE"
                
                # Gestion SMS (Format: sms 0612345678 message)
                elif cmd.startswith("sms"):
                    parts = cmd.split(" ", 2)
                    if len(parts) >= 3:
                        self.api.send_sms(parts[1], parts[2])
                        print(f"| Diablo |: SMS envoyé vers {parts[1]}")
                
                # Commandes Système
                elif "update" in cmd: self.brain_c.check_update()
                elif "stats" in cmd:
                    print(f"| Diablo |: Actions totales enregistrées: {self.memory.data['stats']['actions']}")

                if action:
                    self.api.execute(action)
                    self.memory.learn(action)
                    print(f"| Diablo |: Action {action} exécutée.")

            except KeyboardInterrupt: break
            except Exception as e: print(f"Erreur : {e}")

if __name__ == "__main__":
    DiabloOS().start()
