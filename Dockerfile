# --- Base image ---
FROM python:3.11-slim

# --- Set working directory ---
WORKDIR /app

# --- Install basic system dependencies ---
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    apt-transport-https \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- Copy application files ---
COPY . /app

# --- Install Python dependencies ---
RUN pip install --upgrade pip
RUN if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi

# --- Set environment variables (optional, adjust as needed) ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- Default command ---
CMD ["python", "main.py"]
