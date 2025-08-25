FROM python:3.11-slim

# Env vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CHROME_BIN=/usr/bin/google-chrome-stable \
    CHROMEDRIVER_PATH=/usr/local/bin/chromedriver

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    wget curl unzip gnupg ca-certificates \
    fonts-liberation libasound2 libatk-bridge2.0-0 libdrm2 libgtk-3-0 \
    libnspr4 libnss3 libxss1 libgbm1 xvfb build-essential \
    # חבילות אופציונליות (בדביאן 12 קיימות, ב-13 אולי לא)
    software-properties-common apt-transport-https || true && \
    rm -rf /var/lib/apt/lists/*

# Add Google Chrome repo (בלי apt-key!)
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/* && \
    google-chrome-stable --version

# Install ChromeDriver תואם
RUN CHROME_VERSION=$(google-chrome-stable --version | sed 's/Google Chrome //g' | cut -d '.' -f 1-3) && \
    echo "Chrome version: $CHROME_VERSION" && \
    DRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_VERSION%.*}") && \
    echo "Driver version: $DRIVER_VERSION" && \
    wget -O /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip" && \
    unzip /tmp/chromedriver.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm /tmp/chromedriver.zip

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

# Copy app
COPY . .

RUN mkdir -p logs automatic_coupon_update/input_html && \
    chmod +x /usr/local/bin/chromedriver && \
    chmod -R 755 /app

# Non-root user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:10000/ || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "4", "--timeout", "300", "--worker-class", "sync", "wsgi:app"]
