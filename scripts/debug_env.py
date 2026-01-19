from app.core.config import settings
import os
from dotenv import load_dotenv

load_dotenv()

print("--- Environment Debug ---")
print(f"OS Environment REDIS_URL: {os.getenv('REDIS_URL')}")
print(f"Settings Class REDIS_URL: {settings.REDIS_URL}")
print("-------------------------")

if "localhost" in settings.REDIS_URL:
    print("⚠️ WARNING: Still pointing to localhost!")
else:
    print("✅ SUCCESS: Pointing to Railway/Remote Redis.")
