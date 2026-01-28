import redis
import sys
import os
from dotenv import load_dotenv

# Load local .env
load_dotenv()

# Use REDIS_URL from environment or default to localhost
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

print(f"Testing connection to: {redis_url}")

try:
    # 1. Test Sync Connection (used by RQ Worker)
    r_sync = redis.from_url(redis_url)
    r_sync.ping()
    print("✅ Sync Redis connection successful!")

    # 2. Test Basic Set/Get
    r_sync.set("test_key", "hello_redis")
    value = r_sync.get("test_key")
    if value.decode('utf-8') == "hello_redis":
        print("✅ Redis Data Write/Read successful!")
    
    r_sync.delete("test_key")

except redis.ConnectionError as e:
    print(f"❌ Could not connect to Redis: {e}")
    print("\nTip: If testing locally, make sure Redis is running.")
    print("If you have Homebrew, run: brew services start redis")
    sys.exit(1)
except Exception as e:
    print(f"❌ An error occurred: {e}")
    sys.exit(1)
