# Multi-Genie Slack Bot

A Slack bot that connects to **multiple Databricks Genie spaces** with per-user **On-Behalf-Of (OBO) authentication**, so every query runs with the Slack user's own Databricks permissions (Unity Catalog row filters, column masks, table grants).

## Features

- **Multi-Genie routing** — channel mapping, `[alias]` prefix, thread continuity, optional AI classifier, interactive picker fallback
- **OBO authentication** — OAuth U2M (PKCE) flow links each Slack user to their Databricks identity; queries execute with their permissions
- **Service-principal fallback** — set `AUTH_MODE=service_principal` for a simpler shared-identity mode
- **Threaded conversations** — maintains Genie conversation context within Slack threads
- **Feedback loop** — thumbs-up / thumbs-down buttons that write back to Genie
- **Encrypted token storage** — Fernet-encrypted local file (swap for Delta table / Secrets in production)

## Architecture

```
Slack user ──► Slack Bot (socket mode)
                  │
                  ├── OBO auth gate (is user linked?)
                  │     NO → send OAuth link → Databricks login → callback → store tokens
                  │     YES → get user's access_token (refresh if expired)
                  │
                  ├── Genie Router
                  │     1. [alias] prefix
                  │     2. Channel → alias map
                  │     3. Thread continuity
                  │     4. AI classifier (optional)
                  │     5. Interactive picker (fallback)
                  │
                  └── GenieClient(space_id, user_token)
                        → Genie API as the user
                        → UC enforces per-user permissions
```

## Quick Start (Local Development)

### 1. Prerequisites

- Python 3.11+
- A Databricks workspace with at least one Genie space
- A Slack app with socket mode enabled ([setup guide](https://www.databricksters.com/p/integrate-slack-with-genie-natively))
- [ngrok](https://ngrok.com/) (or similar) to expose the OAuth callback locally

### 2. Install

```bash
cd multi-genie-slack
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your Slack tokens, Databricks host, Genie space IDs, etc.
```

Generate an encryption key for the local token store:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste the output into TOKEN_ENCRYPTION_KEY in .env
```

### 4. Expose OAuth callback (OBO mode)

```bash
ngrok http 3000
# Copy the https://...ngrok.io URL → set OAUTH_REDIRECT_URI=https://...ngrok.io/callback in .env
```

### 5. Run

```bash
python app.py
```

The bot starts two servers:
- **Flask** on port 3000 — serves `/health`, `/auth/start`, `/callback`
- **Slack socket mode** — listens for Slack events in real time

### 6. Test in Slack

- **DM the bot** — triggers OBO auth prompt on first message
- **Click "Connect Databricks"** — completes OAuth flow
- **Ask a question** — `[sales] What are top 10 customers?`
- **Or use channels** — if you mapped a channel in `CHANNEL_GENIE_MAP`

## Service-Principal Mode (simpler, no per-user auth)

Set `AUTH_MODE=service_principal` in `.env`. The bot uses the Databricks SDK's
auto-detected credentials (PAT or SP) for all queries. No OAuth flow, no token
management — but all users share the same data permissions.

## Deploy to Databricks Apps

1. Create a Databricks App and note the service principal
2. Grant the SP **CAN RUN** on all Genie spaces, **CAN USE** on warehouses, **SELECT** on UC tables
3. Enable **user authorization** on the app and add scopes: `dashboards.genie`, `sql`
4. Update `app.yaml` with your values
5. Upload all files to a workspace folder and deploy

## File Structure

```
app.py             Main entry — Flask + Slack socket mode
config.py          Environment-based configuration
oauth_server.py    Flask routes for OAuth U2M PKCE flow
token_store.py     Encrypted local token storage
genie_client.py    Databricks Genie API client (OBO + SP)
genie_router.py    Multi-space routing logic
slack_bot.py       Slack event handlers and message formatting
app.yaml           Databricks App deployment config
.env.example       Template for local environment variables
requirements.txt   Python dependencies
```
