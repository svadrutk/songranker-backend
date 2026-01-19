from app.core.config import settings
import os
from dotenv import load_dotenv

load_dotenv()

print(f"--- Environment Debug ---")
print(f"OS Environment REDIS_URL: {os.getenv('REDIS_URL')}")
print(f"Settings Class REDIS_URL: {settings.REDIS_URL}")
print(f"-------------------------")

if "localhost" in settings.REDIS_URL:
    print("⚠️ WARNING: Still pointing to localhost!")
else:
    print("✅ SUCCESS: Pointing to Railway/Remote Redis.")
