import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DIRECTOR_IDS = {int(x) for x in os.getenv("DIRECTOR_IDS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "center.db")
