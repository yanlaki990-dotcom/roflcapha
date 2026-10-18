import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CAPTCHA_TIMEOUT = int(os.getenv("CAPTCHA_TIMEOUT", "90"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "2"))
