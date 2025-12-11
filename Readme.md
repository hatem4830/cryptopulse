
# Telegram Crypto Price Bot (Completed)

This repository contains a production-ready Telegram Crypto Price Bot in Python.
It supports:
- On-demand price queries (/price, /coins).
- Subscriptions for periodic updates (/subscribe, /unsubscribe, /list).
- Per-chat threshold alerts (/alert, /alerts, /delalert).
- Multi-currency support (USD default, configurable per-subscription).
- Background worker to send scheduled updates and trigger alerts.
- Persistence using SQLModel (Postgres recommended; SQLite supported for dev).
- Webhook mode (FastAPI + Uvicorn) with automatic webhook registration if TELEGRAM_WEBHOOK_URL is set.
- Polling fallback mode (long polling) if webhook is not configured.
- Docker + docker-compose setup.

Quick steps to run (Docker, recommended)
1. Copy `.env.example` to `.env` and set TELEGRAM_TOKEN (required) and other vars.
2. Build & start:
   docker-compose up --build -d
3. If using webhook mode, ensure TELEGRAM_WEBHOOK_URL is set to an HTTPS URL reachable by Telegram (e.g. via ngrok)
   Example for ngrok:
     ngrok http 8000
   Then set TELEGRAM_WEBHOOK_URL to `<ngrok-url>/webhook/<BOT_TOKEN>` and restart the app with `--webhook` mode.

Run locally (without Docker)
1. Create a virtualenv and install:
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
2. Copy `.env.example` -> `.env` and fill TELEGRAM_TOKEN.
3. For polling mode (default):
   python -m app.main
4. For webhook mode:
   python -m app.main --webhook
   Ensure TELEGRAM_WEBHOOK_URL is set to the URL Telegram should call (including /webhook/<BOT_TOKEN>).

Notes and tips
- Use Postgres in production (DATABASE_URL default in .env.example is for docker-compose).
- For webhooks, your endpoint must be HTTPS. ngrok is handy for local testing.
- The app will automatically set Telegram webhook at startup if TELEGRAM_WEBHOOK_URL is set; it will remove the webhook at shutdown.
- For production, run via Docker or systemd. Example systemd unit is included in systemd/telegram-crypto-bot.service.
- If you change the webhook URL, restart the app so it re-registers the webhook.

If you want, next I can:
- Add Alembic migrations.
- Add CI (GitHub Actions) to build and push the Docker image and run tests.
- Add Prometheus metrics & a /health + /metrics endpoint.
- Add automated tests.
