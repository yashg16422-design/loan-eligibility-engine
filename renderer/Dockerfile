# Slim headless-Chromium renderer for JS-rendered lender pages.
# python:3.12-slim + pinned Playwright + ONLY the headless shell (not full Chrome,
# Firefox or WebKit) keeps the image small enough for a 20 GB t4g.small.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install playwright==1.63.0 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user: a browser engine parses untrusted pages.
RUN useradd --create-home --uid 10001 renderer
WORKDIR /app
COPY url_safety.py server.py ./
USER renderer
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/healthz', timeout=3)"
CMD ["python", "server.py"]
