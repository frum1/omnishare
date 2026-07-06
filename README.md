# OmniShare

Self-hosted file sharing service. Upload a file, get a link back — with a
twist: every upload returns both a public link (your domain) and a local
link (your server's LAN IP), so sharing still works inside your home network
even when the public domain isn't reachable from it.

Built with FastAPI, SQLAlchemy (async) + SQLite, and JWT auth.

## Quick start

```bash
uv sync

cp .env.example .env
# edit .env: PUBLIC_BASE_URL, SECRET_KEY (see inline comments)

# run the server
uv run main.py
```

On first boot the server creates a root `admin` account automatically and
prints its generated password to the console — grab it from there and change
it after logging in.

Swagger/ReDoc are disabled by default (reduces attack surface on a
publicly-exposed instance). For local API exploration, temporarily set
`docs_url`/`redoc_url`/`openapi_url` back in `app/main.py`'s `FastAPI(...)` call.

## Docker

```bash
cp .env.example .env
# edit .env: PUBLIC_BASE_URL, SECRET_KEY (see inline comments)

docker compose up -d
```

The container uses host networking (Linux) so the "local link" auto-detection
sees your machine's real LAN IP — no port mapping needed, the service is
reachable on `LOCAL_PORT` (default 8000) directly. Persistent data lives in
bind mounts next to the compose file: `data/` (SQLite DB), `storage/`
(uploaded files), and `.env` itself — settings changed via the admin panel
are written back into it, so it's bind-mounted (not just passed as
`env_file:`) to survive container recreation.

Grab the generated admin password from the logs on first boot:

```bash
docker compose logs omnishare
```

Lost the admin password? Reset it without touching the database by hand:

```bash
docker compose exec omnishare python -m scripts.reset_admin_password
```

**Not on Linux?** Host networking isn't available on Docker Desktop
(macOS/Windows). See the commented bridge-network block in
`docker-compose.yml` and set `LOCAL_BASE_URL` explicitly in `.env`.

## Public HTTPS (domain + certificate)

To expose OmniShare on the internet under your own domain with a trusted
certificate, run the bundled Caddy reverse proxy — it obtains and renews a
Let's Encrypt certificate automatically, no certbot or manual renewal.

Prerequisites:

- A domain (or subdomain) with DNS pointed at this server's public IP.
- Ports **80** and **443** forwarded to this machine on your router/firewall
  (80 is required for the ACME challenge, not just for redirects).

Setup:

```bash
# in .env:
# DOMAIN=share.example.com
# PUBLIC_BASE_URL=https://share.example.com

docker compose --profile proxy up -d
```

That starts `omnishare` plus a `caddy` container reading `Caddyfile`, which
proxies `https://$DOMAIN` to the app and handles the certificate. Without
`--profile proxy`, Caddy is skipped entirely and the previous plain-HTTP setup
is unchanged.

Copyleft frum1 :)
2026-20xx
