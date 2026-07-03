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

Open `http://localhost:8000/docs` for interactive API docs.
