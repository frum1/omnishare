from pathlib import Path

ENV_PATH = Path(".env")


def update_env_file(updates: dict[str, str], env_path: Path = ENV_PATH) -> None:
    remaining = dict(updates)
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    # Written in place rather than write-tmp-then-rename: in Docker .env is
    # typically bind-mounted as a single file, which is itself a mount point,
    # so renaming another file onto it fails with EBUSY ("device or resource
    # busy"). A plain in-place write has no such restriction.
    env_path.write_text("\n".join(new_lines) + "\n")
