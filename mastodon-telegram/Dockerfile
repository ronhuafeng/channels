FROM --platform=linux/amd64 python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml uv.lock ./

# Install uv (fast Python package installer)
RUN pip install uv

# Install dependencies using uv
RUN uv sync --frozen

# Copy the application code
COPY main.py ./

# Create directory for the database
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_NAME=/app/data/synced_posts.db

# Run the application
CMD ["uv", "run", "python", "main.py"]
