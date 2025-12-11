
FROM python:3.11-slim

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port for webhook mode
EXPOSE 8000

# Default: run in polling mode for ease of dev.
# Pass --webhook to enable webhook mode (also set TELEGRAM_WEBHOOK_URL)
CMD ["python", "-m", "app.main"]
