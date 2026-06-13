# Pinned to bookworm: the Camoufox system deps below use Debian bookworm
# package names (e.g. libasound2, not the trixie/noble libasound2t64).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1

# Camoufox (headless Firefox) runtime libraries — mirrors noted's proven set.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgtk-3-0 libdbus-glib-1-2 libasound2 libx11-xcb1 libxcomposite1 \
        libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libatk1.0-0 \
        libxshmfence1 libxfixes3 libxtst6 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install deps, then download the Camoufox browser build at image-build time
# (needs network; the build stage has it) so the container starts offline-ready.
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m camoufox fetch

COPY app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
