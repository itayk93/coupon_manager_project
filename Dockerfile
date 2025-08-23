# Multi-stage build for Render deployment with Chrome and Selenium support
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CHROME_BIN=/usr/bin/google-chrome-stable \
    CHROMEDRIVER_PATH=/usr/local/bin/chromedriver

# Create app directory
WORKDIR /app

# Install system dependencies and Chrome
RUN apt-get update && apt-get install -y \
    # Basic system tools
    wget \
    curl \
    unzip \
    gnupg \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    # For Chrome
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxss1 \
    libgbm1 \
    # For virtual display (if needed)
    xvfb \
    # For build tools
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/* && \
    # Debug: Check if Chrome was installed correctly
    ls -la /usr/bin/google-chrome* || echo "Chrome not found in /usr/bin/" && \
    which google-chrome-stable || echo "google-chrome-stable not in PATH" && \
    google-chrome-stable --version || echo "Cannot run Chrome"

# Install ChromeDriver
RUN CHROME_VERSION=$(google-chrome --version | sed 's/Google Chrome //g' | cut -d '.' -f 1-3) && \
    echo "Chrome version: $CHROME_VERSION" && \
    DRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_VERSION%.*}") && \
    echo "Driver version: $DRIVER_VERSION" && \
    wget -O /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip" && \
    unzip /tmp/chromedriver.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm /tmp/chromedriver.zip

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # Install Playwright browsers
    playwright install --with-deps chromium

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs automatic_coupon_update/input_html

# Set proper permissions
RUN chmod +x /usr/local/bin/chromedriver && \
    chmod -R 755 /app

# Create a non-root user for running the application
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:10000/ || exit 1

# Default command for web service
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "4", "--timeout", "300", "--worker-class", "sync", "wsgi:app"]