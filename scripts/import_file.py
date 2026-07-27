"""Registers a file that's already sitting on this machine as a share,
without going through the HTTP upload API - for when the file got here some
other way (scp'd next to the service, dropped into a bind mount, etc.) and
routing it through the network a second time would be pointless.

Run: python -m scripts.import_file FILE [options]
    (owner defaults to the root admin account "admin")

Run inside the container if using Docker:
    docker compose exec omnishare python -m scripts.import_file /app/storage/incoming/movie.mkv
"""
import argparse
import asyncio
import mimetypes
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.network import build_share_urls
from app.core.storage import build_storage_path
from app.db.models import User
from app.db.session import async_session_maker, init_db
from app.services.bootstrap import ROOT_ADMIN_USERNAME
from app.services.uploads import build_file_share


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="path to the file to import")
    parser.add_argument("--owner", default=ROOT_ADMIN_USERNAME, help="username to own the file (default: %(default)s)")
    parser.add_argument("--caption")
    parser.add_argument("--ttl", type=int, help="seconds until the link expires (omit = never)")
    parser.add_argument("--max-downloads", type=int)
    parser.add_argument("--move", action="store_true", help="move the source file instead of copying it")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"Not a file: {args.file}")
        return

    await init_db()

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == args.owner))
        owner = result.scalar_one_or_none()
        if owner is None:
            print(f"User '{args.owner}' not found.")
            return

        file_id = uuid.uuid4().hex
        created_at = datetime.utcnow()
        dest = build_storage_path(file_id, created_at)
        dest.parent.mkdir(parents=True, exist_ok=True)

        size_bytes = args.file.stat().st_size
        content_type = mimetypes.guess_type(args.file.name)[0] or "application/octet-stream"

        if args.move:
            shutil.move(str(args.file), dest)
        else:
            shutil.copy2(args.file, dest)

        session.add(
            build_file_share(
                file_id=file_id,
                owner_id=owner.id,
                original_filename=args.file.name,
                stored_path=str(dest),
                content_type=content_type,
                size_bytes=size_bytes,
                caption=args.caption,
                created_at=created_at,
                ttl_seconds=args.ttl,
                max_downloads=args.max_downloads,
            )
        )
        await session.commit()

    urls = build_share_urls(file_id)
    print("=" * 50)
    print("  FILE IMPORTED")
    print(f"  Owner:  {args.owner}")
    print(f"  Public: {urls['public_url']}")
    print(f"  Local:  {urls['local_url']}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
