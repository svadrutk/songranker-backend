#!/bin/bash

# Development script for hot reloading
# Usage: ./dev.sh [up|down|restart|logs]

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml"

case "$1" in
  up)
    echo "Starting development environment with hot reloading..."
    shift
    docker-compose $COMPOSE_FILES up "$@"
    ;;
  down)
    echo "Stopping development environment..."
    docker-compose $COMPOSE_FILES down
    ;;
  restart)
    echo "Restarting development environment..."
    docker-compose $COMPOSE_FILES restart
    ;;
  logs)
    docker-compose $COMPOSE_FILES logs -f "${2:-web}"
    ;;
  build)
    echo "Rebuilding containers..."
    docker-compose $COMPOSE_FILES build
    ;;
  *)
    echo "Usage: $0 {up|down|restart|logs|build}"
    echo ""
    echo "Commands:"
    echo "  up       - Start services with hot reloading (pass -d for detached)"
    echo "  down     - Stop all services"
    echo "  restart  - Restart services"
    echo "  logs     - Follow logs (optionally specify service: logs web)"
    echo "  build    - Rebuild containers"
    exit 1
    ;;
esac
