from datetime import datetime
from pathlib import Path

from app.core.config import settings


def build_storage_path(file_id: str, created_at: datetime) -> Path:
    """storage/<год>/<месяц>/<день>/<2 символа id>/<file_id>.

    Дата ограничивает размер директории естественным темпом загрузок, а
    хэш-шард (первые байты id - у uuid4 они равномерно случайны) защищает от
    раздутия даже при большом числе загрузок за один день.
    """
    date_dir = created_at.strftime("%Y/%m/%d")
    shard = file_id[:2]
    return settings.storage_path / date_dir / shard / file_id


def cleanup_empty_parents(path: Path) -> None:
    """Убирает опустевшие после удаления файла родительские директории
    (шард/день/месяц/год), не трогая сам storage_path."""
    root = settings.storage_path.resolve()
    parent = path.resolve().parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
