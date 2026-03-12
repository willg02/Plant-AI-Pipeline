import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/plants.db")
CLAUDE_MODEL = "claude-3-haiku-20240307"
PORT = int(os.getenv("PORT", 8000))
