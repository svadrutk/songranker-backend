# Use official Python 3.13 slim image
FROM python:3.13-slim-bookworm

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Copy project configuration files
COPY pyproject.toml .

# Install Python dependencies
# We install the package in editable mode or just the deps
RUN pip install --upgrade pip && \
    pip install .

# Install Playwright browsers and system dependencies
# This is crucial for the image generation feature
RUN playwright install chromium && \
    playwright install-deps chromium

# Copy the rest of the application
COPY . .

# Expose the port
EXPOSE 8000

# Run the application
# Railway passes the PORT env var, but gunicorn needs it explicitly passed or we rely on the shell expansion
CMD sh -c "gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --timeout 120 --keep-alive 5"
