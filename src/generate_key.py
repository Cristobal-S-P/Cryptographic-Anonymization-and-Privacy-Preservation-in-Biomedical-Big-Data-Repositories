from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet

from .config import MASTER_KEY_PATH


def generate_master_key(path: Path = MASTER_KEY_PATH) -> Path:
    """Create a Fernet master key without replacing an existing key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"Ya existe una clave en {path}; no se modificó.") from exc

    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(key)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera una clave maestra Fernet nueva sin sobrescribir claves."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=MASTER_KEY_PATH,
        help="Ruta local para guardar la clave (default: keys/master.key).",
    )
    args = parser.parse_args()

    try:
        key_path = generate_master_key(args.path)
    except FileExistsError as exc:
        parser.error(str(exc))
    print(f"Clave maestra creada localmente en: {key_path}")


if __name__ == "__main__":
    main()
