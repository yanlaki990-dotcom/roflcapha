import json
import os
import logging

log = logging.getLogger(__name__)
DATA_FILE = os.getenv("DATA_FILE", "pending.json")

pending: dict = {}

def save():
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        log.warning(f"storage save failed: {e}")

def load():
    global pending
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            pending = json.load(f)
        log.info(f"Loaded {len(pending)} pending captchas")
    except Exception as e:
        log.warning(f"storage load failed: {e}")
        pending = {}
