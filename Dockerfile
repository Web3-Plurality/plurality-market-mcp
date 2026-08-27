# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files (README.md needed by hatchling build backend)
COPY pyproject.toml uv.lock README.md ./

# Install uv and project dependencies
RUN pip install --no-cache-dir uv && uv sync --frozen

# Copy application code
COPY main.py .
COPY src/ src/

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose port
EXPOSE 5051

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5051/mcp || exit 1

# Run the application
CMD ["uv", "run", "uvicorn", "main:mcp_server", "--host", "0.0.0.0", "--port", "5051"]
