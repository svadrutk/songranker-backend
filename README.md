# SongRanker Backend

A FastAPI backend for the SongRanker application, providing a secure bridge to external APIs like Discogs.

## Tech Stack

- **Python 3.13+**
- **FastAPI**: Modern, fast web framework.
- **uv**: Extremely fast Python package installer and resolver.
- **httpx**: Modern HTTP client for asynchronous requests.
- **Ruff**: Fast Python linter and formatter.

## Setup

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Configure Environment**:
   Copy `.env.example` to `.env` and fill in your Discogs credentials:
   ```bash
   cp .env.example .env
   ```

## Running the Server

Start the development server with:
```bash
uv run uvicorn app.main:app --reload
```

Or using the entry point script:
```bash
uv run main.py
```

The API will be available at `http://localhost:8000`.
Swagger documentation can be found at `http://localhost:8000/docs`.

## Development

- **Linting & Formatting**:
  ```bash
  uv run ruff check .
  uv run ruff format .
  ```
