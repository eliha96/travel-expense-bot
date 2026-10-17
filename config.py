import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
RECEIPTS_DIR = DATA_DIR / "receipts"
RECEIPTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Database
DB_PATH = DATA_DIR / "expenses.db"

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Travel Expense Settings
ORIGIN_ADDRESS = os.getenv("ORIGIN_ADDRESS", "הכ\"ג 5, הרצליה")
RATE_PER_KM = float(os.getenv("RATE_PER_KM", "1.40"))

# Authorized Telegram User ID (Optional security lock so only the owner can use the bot)
AUTHORIZED_USER_ID = os.getenv("AUTHORIZED_USER_ID", "")
