import json
import sys
from pathlib import Path

# Add the project root to sys.path
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))

try:
    from app.main import app
except ImportError as e:
    print(f"Error importing app: {e}")
    sys.exit(1)

def export_openapi():
    # Get the OpenAPI schema
    openapi_schema = app.openapi()
    
    # Define the output path in the frontend directory
    # songranker-backend/scripts/export_openapi.py -> songranker-frontend/openapi.json
    output_path = root_path.parent / "songranker-frontend" / "openapi.json"
    
    # Ensure the directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write the schema
    with open(output_path, "w") as f:
        json.dump(openapi_schema, f, indent=2)
    
    print(f"OpenAPI schema exported to {output_path}")

if __name__ == "__main__":
    export_openapi()
