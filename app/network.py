import socket

from app.config import settings


def detect_local_ip() -> str:
    """Определяет IP локального интерфейса, через который сервер выходит наружу.

    Сокет не отправляет ни одного пакета - connect() на UDP лишь выбирает
    маршрут/интерфейс ядром ОС, поэтому это работает даже без интернета,
    пока есть хоть какая-то сеть (например 192.168.x.x).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_local_base_url() -> str:
    if settings.local_base_url:
        return settings.local_base_url.rstrip("/")
    ip = detect_local_ip()
    return f"http://{ip}:{settings.local_port}"


def build_share_urls(file_id: str) -> dict:
    return {
        "public_url": f"{settings.public_base_url.rstrip('/')}/f/{file_id}",
        "local_url": f"{get_local_base_url()}/f/{file_id}",
    }
