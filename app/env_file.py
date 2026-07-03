from pathlib import Path

ENV_PATH = Path(".env")


def update_env_file(updates: dict[str, str], env_path: Path = ENV_PATH) -> None:
    """Точечно обновляет KEY=value строки в .env, сохраняя остальное содержимое
    (комментарии, порядок, недостающие ключи допишет в конец) и пишет атомарно."""
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

    tmp_path = env_path.with_name(env_path.name + ".tmp")
    tmp_path.write_text("\n".join(new_lines) + "\n")
    tmp_path.replace(env_path)
