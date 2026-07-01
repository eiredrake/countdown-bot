from pathlib import Path
from dotenv import load_dotenv
import os

# Load .env from the project root
load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)