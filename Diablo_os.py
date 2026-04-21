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
# CONFIGURATION
# =========================
VERSION = "3.0.0"
MEMORY_FILE = "diablo_neural_memory.json"
# Lien direct vers votre fichier sur GitHub
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
        if patterns[best_action] >= 5: # Seuil d'apprentissage
            return best_action
        return None

# =========================
# CERVEAUX ET LOGIQUE
# =========================
class ExecutiveBrain:
    def __init__(self, api, memory):
        self.api, self.memory = api, memory
        self.is_running = True

    def run(self):
        while self.is_running:
            try:
                bat = self.api.get_battery().get("percentage", 100)
                if bat < 15: self.api.execute("BRIGHT_LOW")
                
                prediction = self.memory.get_prediction()
                if prediction:
                    self.api.execute(prediction)
            except: pass
            time.sleep(60)

class MaintenanceBrain:
    def check_update(self):
        try:
            r = requests.get(UPDATE_URL, timeout=10)
            if r.status_code == 200:
                # Vérifie si le numéro de version dans le code distant est différent
                if f'VERSION = "{VERSION}"' not in r.text:
                    self.apply_update(r.text)
        except: pass

    def apply_update(self, content):
        print(f"\n[Maintenance] Nouvelle version trouvée. Installation...")
        with open(__file__, "w") as f:
            f.write(content)
        print("[Maintenance] Redémarrage...")
        os.execv(sys.executable, ['python'] + sys.argv)

    def run(self):
        while True:
            self.check_update()
            time.sleep(1800) # Vérifie toutes les 30 minutes

class SupervisorBrain:
    def __init__(self, b_a, b_c):
        self.b_a, self.b_c = b_a, b_c

    def run(self):
        while True:
            if not self.b_a.is_running: self.b_a.is_running = True
            time.sleep(60)

# =========================
# API & CORE
# =========================
class TermuxAPI:
    def execute(self, action):
        cmds = {
            "TORCH_ON": ["termux-torch", "on"],
            "TORCH_OFF": ["termux-torch", "off"],
            "BRIGHT_LOW": ["termux-brightness", "10"],
            "PHOTO": ["termux-camera-photo", "-c", "0", "/sdcard/diablo_auto.jpg"]
        }
        if action in cmds:
            subprocess.Popen(cmds[action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def get_battery(self):
        try: return json.loads(subprocess.check_output(["termux-battery-status"], timeout=2))
        except: return {}

class DiabloOS:
    def __init__(self):
        self.api = TermuxAPI()
        self.memory = NeuralMemory()
        self.brain_a = ExecutiveBrain(self.api, self.memory)
        self.brain_c = MaintenanceBrain()
        self.brain_b = SupervisorBrain(self.brain_a, self.brain_c)

    def start(self):
        os.system("clear")
        print(f"DIABLO OS v{VERSION}")
        print(f"Lien Update: {UPDATE_URL}")
        
        for thread in [self.brain_a.run, self.brain_b.run, self.brain_c.run]:
            threading.Thread(target=thread, daemon=True).start()

        while True:
            cmd = input(f"Diablo@{VERSION} # ").lower()
            if cmd in ["exit", "update"]:
                if cmd == "update": self.brain_c.check_update()
                break
            
            action = None
            if "on" in cmd: action = "TORCH_ON"
            elif "off" in cmd: action = "TORCH_OFF"
            
            if action:
                self.api.execute(action)
                self.memory.learn(action)

if __name__ == "__main__":
    DiabloOS().start()
