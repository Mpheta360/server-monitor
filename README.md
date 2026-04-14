# System Monitor MVP (FastAPI + Supabase + Agent)

This project is a starter monitoring platform for servers and systems.

## What You Get

- FastAPI backend for metric ingestion and server health APIs
- Supabase Postgres-backed data model (SQLAlchemy)
- Supabase Auth-backed mobile API protection (Bearer access token)
- Lightweight Python agent to collect CPU, memory, disk, load, uptime, service status, and optional Nginx stats
- Basic dashboard at `/` for live overview and server table
- Threshold-based critical state detection
- Optional email, Telegram, and webhook alert delivery with cooldown

## Project Structure

- `backend/` FastAPI API + dashboard
- `agent/` collector script you run on servers
- `docker-compose.yml` local PostgreSQL service (optional local fallback)

## 1) Configure Supabase (Database + Auth)

Create a Supabase project, then copy values into `backend/.env`:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_DB_URL` (pooler connection string, include `sslmode=require`)

Optional local-only DB fallback:

```bash
docker compose up -d
# then set DATABASE_URL in backend/.env
```

## 2) Run Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Backend defaults:

- API docs: `http://127.0.0.1:8000/docs`
- Dashboard: `http://127.0.0.1:8000/`

## 3) Run Agent (same machine or another server)

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python agent.py
```

Agent Nginx options (in `agent/.env`):

- `MONITOR_NGINX_ENABLED=true`
- `MONITOR_NGINX_STATUS_URL=http://127.0.0.1:8080/nginx_status`
- `MONITOR_NGINX_VERIFY_TLS=true`

## Authentication

If `INGEST_API_TOKEN` is set in `backend/.env`, the agent must send the same token in `MONITOR_API_TOKEN`.

Mobile API authentication uses Supabase access tokens. The backend verifies bearer tokens against Supabase Auth at `/auth/v1/user`.

Admin web/dashboard and server API endpoints require HTTP Basic Auth (`ADMIN_USERNAME` / `ADMIN_PASSWORD`).

## Alerts

Configure alert sinks in `backend/.env`:

- `ALERT_COOLDOWN_SECONDS` to avoid repeating the same alert too often
- `ALERT_WEBHOOK_URL` for any webhook receiver
- `ALERT_EMAIL_TO` comma-separated email recipients
- `ALERT_EMAIL_FROM` sender email address
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`
- `SMTP_USE_TLS` or `SMTP_USE_SSL` based on provider
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for Telegram delivery

If `ALERT_EMAIL_TO` is empty, the system falls back to `SMTP_USERNAME` as the recipient (if it looks like an email).

Example email config:

```env
ALERT_EMAIL_TO=ops@yourdomain.com,devops@yourdomain.com
ALERT_EMAIL_FROM=monitor@yourdomain.com
SMTP_HOST=smtp.yourdomain.com
SMTP_PORT=587
SMTP_USERNAME=monitor@yourdomain.com
SMTP_PASSWORD=your-app-password
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

## React Native API Endpoints

All endpoints below require `Authorization: Bearer <supabase_access_token>`.

- `GET /api/v1/mobile/me`
- `GET /api/v1/mobile/bootstrap?server_limit=30&alerts_limit=30`
- `GET /api/v1/mobile/servers?status=critical&search=web&limit=20&offset=0`
- `GET /api/v1/mobile/servers/{server_id}`
- `GET /api/v1/mobile/servers/{server_id}/metrics?minutes=180`
- `GET /api/v1/mobile/servers/{server_id}/nginx-metrics?minutes=180`
- `GET /api/v1/mobile/alerts?limit=50&server_id=1`

Server API endpoint for Nginx timeline:

- `GET /api/v1/servers/{server_id}/nginx-metrics?minutes=180`

## Nginx Monitoring Setup

Enable `stub_status` on each Nginx host:

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

Then reload Nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Monitoring Hosted Systems (Your Infrastructure)

For every hosted VM/server, install and run the agent so it pushes metrics to this central API.

Suggested rollout:

1. Deploy API on one central server (public/private reachable URL).
2. On each hosted system, copy `agent/` and set `MONITOR_API_URL` to the central ingest endpoint.
3. Set per-host tags in `MONITOR_TAGS` (for example `prod,web,zone-a`).
4. Run agent as a `systemd` service for auto-restart.

Example service file (`/etc/systemd/system/monitor-agent.service`):

```ini
[Unit]
Description=System Monitor Agent
After=network.target

[Service]
User=root
WorkingDirectory=/opt/monitor/agent
ExecStart=/opt/monitor/agent/.venv/bin/python /opt/monitor/agent/agent.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/monitor/agent/.env

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-agent
sudo systemctl status monitor-agent
```

## Host It (Production)

This repo now includes a production stack:

- `backend/Dockerfile` for API container
- `docker-compose.host.yml` for backend + Caddy reverse proxy
- `deploy/Caddyfile` for automatic HTTPS (Let's Encrypt)
- `.env.host.example` for domain config
- `scripts/deploy-host.sh` and `scripts/host-logs.sh`

### Prerequisites

1. VPS/server with Docker + Docker Compose installed.
2. Domain/subdomain pointing to your server IP (A record), for example `monitor.yourdomain.com`.
3. Open firewall ports `80` and `443`.
4. Configure `backend/.env` with real Supabase + alert credentials.
5. Set secure admin credentials and tight CORS/hosts:
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD`
   - `CORS_ALLOW_ORIGINS=https://monitor.yourdomain.com`
   - `ALLOWED_HOSTS=monitor.yourdomain.com,localhost,127.0.0.1`
   - `INGEST_API_TOKEN` must be set

### Deploy

```bash
cp .env.host.example .env.host
# edit .env.host and set DOMAIN=monitor.yourdomain.com

chmod +x scripts/deploy-host.sh scripts/host-logs.sh
./scripts/deploy-host.sh
```

### Verify

```bash
docker compose --env-file .env.host -f docker-compose.host.yml ps
./scripts/host-logs.sh
```

When DNS is ready, Caddy automatically provisions TLS certificates and your app is available at:

- `https://<your-domain>/`
- `https://<your-domain>/docs`

### Update Deployment

```bash
git pull
./scripts/deploy-host.sh
```

Example React Native fetch:

```ts
import { createClient } from "@supabase/supabase-js";

const API_BASE = "http://YOUR_SERVER_IP:8000";
const supabase = createClient("https://your-project-ref.supabase.co", "your-anon-key");

async function loadBootstrap() {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const token = session?.access_token;
  if (!token) throw new Error("No Supabase session");

  const response = await fetch(`${API_BASE}/api/v1/mobile/bootstrap`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Bootstrap failed: ${response.status}`);
  }

  return response.json();
}
```

## Ingestion Payload (reference)

```json
{
  "server": {
    "hostname": "web-01",
    "ip_address": "10.0.0.21",
    "environment": "production",
    "tags": ["web", "nginx"]
  },
  "metrics": {
    "cpu_percent": 43.2,
    "memory_percent": 67.5,
    "disk_percent": 54.1,
    "load_1m": 1.3,
    "load_5m": 0.8,
    "load_15m": 0.5,
    "uptime_seconds": 94532
  },
  "services": [
    {"name": "nginx", "status": "running"},
    {"name": "postgresql", "status": "running"}
  ]
}
```

## Next Improvements

1. Add more alert channels (Slack, PagerDuty, SMS) in `backend/app/services/alerts.py`.
2. Add background jobs for retention rollups and cleanup.
3. Add multi-tenant organization support and role-based access checks.
4. Add charts per host with history filters and anomaly detection.
