import uvicorn
import os
import sys

# Add the current directory to sys.path to ensure 'app' is findable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
