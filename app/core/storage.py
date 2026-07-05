from datetime import datetime
from pathlib import Path

from app.core.config import settings


def build_storage_path(file_id: str, created_at: datetime) -> Path:
    """storage/<year>/<month>/<day>/<2 chars of id>/<file_id>.

    The date bounds directory size at the natural upload rate, while the
    hash shard (the first bytes of the id - uniformly random for uuid4)
    guards against bloat even under heavy upload volume on a single day.
    """
    date_dir = created_at.strftime("%Y/%m/%d")
    shard = file_id[:2]
    return settings.storage_path / date_dir / shard / file_id


def build_incomplete_path(upload_id: str) -> Path:
    """Location of an in-progress TUS upload before finalization.

    Kept flat (not sharded) since the set of concurrent unfinished uploads is
    small and short-lived; on completion the file is moved into the sharded
    tree produced by build_storage_path.
    """
    return settings.incomplete_path / upload_id


def cleanup_empty_parents(path: Path) -> None:
    """Removes parent directories (shard/day/month/year) left empty after a
    file is deleted, without touching storage_path itself."""
    root = settings.storage_path.resolve()
    parent = path.resolve().parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
