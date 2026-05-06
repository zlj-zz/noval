import json
import os
import time
from pathlib import Path
from typing import Dict, List

CONFIG_DIR = Path.home() / ".config" / "noval"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config:
    save_dir: str
    default_sep: float
    history: List[Dict]

    def __init__(self):
        self.save_dir = str(Path.home() / "novals")
        self.default_sep = 0.0
        self.history = []
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return
            self.save_dir = data.get("save_dir", self.save_dir)
            self.default_sep = data.get("default_sep", self.default_sep)
            self.history = data.get("history", [])

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "save_dir": self.save_dir,
            "default_sep": self.default_sep,
            "history": self.history,
        }
        CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_history(self, name: str, path: str, url: str):
        self.history = [h for h in self.history if h.get("name") != name]
        self.history.insert(
            0,
            {
                "name": name,
                "path": path,
                "url": url,
                "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.history = self.history[:20]
        self.save()


config = Config()
