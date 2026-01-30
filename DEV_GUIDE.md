# Development Guide

## Hot Reloading Setup

For faster development without rebuilding containers after every change, use the development docker-compose configuration:

### Quick Start

```bash
# Start with hot reloading
./dev.sh up

# Or manually:
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### What Gets Hot Reloaded?

The development setup automatically reloads when you change:
- **Python files** in `app/` directory
- **HTML templates** in `templates/` directory  
- **CSS files** in `static/` directory
- **Worker code** in `worker.py`

### Available Commands

```bash
./dev.sh up       # Start services with hot reloading
./dev.sh down     # Stop all services
./dev.sh restart  # Restart services
./dev.sh logs     # Follow logs (add service name: logs web)
./dev.sh build    # Rebuild containers
```

### How It Works

The `docker-compose.dev.yml` file:
1. Mounts your source code as volumes into the containers
2. Replaces gunicorn with uvicorn in `--reload` mode for the web service
3. Enables auto-reload for templates and static files

Changes to these files are reflected immediately without restarting containers:
- `app/**/*.py` - Python API code
- `templates/*.html` - Jinja2 templates
- `static/**/*` - Static assets

### When Do I Need to Rebuild?

You only need to rebuild (`./dev.sh build`) when:
- Adding new dependencies to `pyproject.toml`
- Changing `Dockerfile`
- Installing new system packages

### Production vs Development

- **Development**: Uses `docker-compose.dev.yml` with volume mounts and uvicorn --reload
- **Production**: Uses base `docker-compose.yml` with gunicorn for better performance

Never deploy the dev configuration to production!
