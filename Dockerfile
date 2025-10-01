FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000 HEADLESS=False \
    SELENIUM_MANAGER_BINARY=off CHROMEDRIVER_PATH=/usr/local/bin/chromedriver

# Base deps + Xvfb
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg wget unzip fontconfig fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 \
    libdrm2 libgbm1 libgtk-3-0 libnss3 libx11-xcb1 libxcomposite1 \
    libxcursor1 libxdamage1 libxfixes3 libxi6 libxrandr2 libxrender1 \
    libxss1 libxtst6 xdg-utils xvfb xauth \
  && rm -rf /var/lib/apt/lists/*

# Google Chrome
RUN mkdir -p /usr/share/keyrings \
  && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
     | gpg --dearmor -o /usr/share/keyrings/google-linux-signing-keyring.gpg \
  && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-signing-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
     > /etc/apt/sources.list.d/google-chrome.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends google-chrome-stable \
  && rm -rf /var/lib/apt/lists/*

# Bake matching chromedriver
RUN set -eux; \
  CHROME_VERSION="$(google-chrome --version | awk '{print $3}')" ; \
  CD_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip"; \
  wget -O /tmp/chromedriver.zip "${CD_URL}"; \
  unzip -q /tmp/chromedriver.zip -d /tmp; \
  install -m 0755 /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
  rm -rf /tmp/chromedriver.zip /tmp/chromedriver-linux64; \
  which chromedriver && chromedriver --version

WORKDIR /app

# Python deps
COPY requirements.txt .
# add pyvirtualdisplay for Xvfb control
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install pyvirtualdisplay

# App
COPY . .

# Writable dirs + non-root
RUN mkdir -p /app/reports /tmp /var/tmp \
  && useradd --create-home --shell /bin/bash appuser \
  && chown -R appuser:appuser /app /tmp /var/tmp /home/appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000","--timeout-keep-alive","1200","--log-level","info"]
