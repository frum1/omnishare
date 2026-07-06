import socket
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings


def detect_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def apply_port(base_url: str, port: int) -> str:
    """Append the configured port to a base URL for use in generated links.

    The same port that hosts the server is reused in the share URLs. If the
    base URL already pins an explicit port (or has no parseable host) it is left
    untouched, so we never produce something like ``http://host:8000:8000``.
    """
    base_url = base_url.rstrip("/")
    parts = urlsplit(base_url)
    if not parts.hostname or parts.port is not None:
        return base_url
    netloc = f"{parts.hostname}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def get_local_base_url() -> str:
    if settings.local_base_url:
        return apply_port(settings.local_base_url, settings.local_port)
    ip = detect_local_ip()
    return f"http://{ip}:{settings.local_port}"


def build_share_urls(file_id: str) -> dict:
    # Unlike the local link, the public URL is never auto-ported: it's
    # reached through a domain (typically behind a reverse proxy on
    # 80/443), so gluing on the app's internal LOCAL_PORT would break it.
    public_base = settings.public_base_url.rstrip("/")
    return {
        "public_url": f"{public_base}/f/{file_id}",
        "local_url": f"{get_local_base_url()}/f/{file_id}",
    }
