import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DIRECTOR_IDS = {int(x) for x in os.getenv("DIRECTOR_IDS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "center.db")
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
TZ_OFFSET = int(os.getenv("TZ_OFFSET", "5"))  # Toshkent UTC+5
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "9"))
