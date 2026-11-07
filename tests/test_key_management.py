from pathlib import Path
import sys

import pytest
from cryptography.fernet import Fernet

import main as app
from src.config import MASTER_KEY_PATH
from src.crypto_utils import CryptoError, IdentityCrypto
from src.generate_key import generate_master_key


def test_generate_master_key_creates_valid_key_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "keys" / "master.key"

    assert generate_master_key(key_path) == key_path
    original_key = key_path.read_bytes()
    Fernet(original_key)

    with pytest.raises(FileExistsError, match="no se modificó"):
        generate_master_key(key_path)

    assert key_path.read_bytes() == original_key


def test_identity_crypto_requires_an_existing_key(tmp_path: Path) -> None:
    key_path = tmp_path / "keys" / "master.key"

    with pytest.raises(FileNotFoundError, match="python -m src.generate_key"):
        IdentityCrypto(key_path)

    assert not key_path.exists()
    assert not key_path.parent.exists()


def test_identity_crypto_recovers_data_with_existing_key(tmp_path: Path) -> None:
    key_path = generate_master_key(tmp_path / "master.key")
    original_key = key_path.read_bytes()

    original_crypto = IdentityCrypto(key_path)
    encrypted_text = original_crypto.encrypt_text("dato previamente cifrado")
    legacy_encrypted_text = Fernet(original_key).encrypt(
        b"formato Fernet anterior"
    ).decode("ascii")
    reloaded_crypto = IdentityCrypto(key_path)

    assert reloaded_crypto.decrypt_text(encrypted_text) == "dato previamente cifrado"
    assert reloaded_crypto.decrypt_text(legacy_encrypted_text) == "formato Fernet anterior"
    assert key_path.read_bytes() == original_key


def test_identity_crypto_rejects_invalid_key_without_replacing_it(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "master.key"
    invalid_key = b"not a Fernet key"
    key_path.write_bytes(invalid_key)

    with pytest.raises(CryptoError, match="no es válida para Fernet"):
        IdentityCrypto(key_path)

    assert key_path.read_bytes() == invalid_key


def test_configured_master_key_path_is_absolute_and_project_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_path = Path(__file__).resolve().parents[1] / "keys" / "master.key"
    monkeypatch.chdir(tmp_path)

    assert MASTER_KEY_PATH.is_absolute()
    assert MASTER_KEY_PATH == expected_path


def test_application_reports_how_to_generate_a_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_key = tmp_path / "missing.key"
    input_csv = tmp_path / "input.csv"
    input_csv.write_text("", encoding="utf-8")
    monkeypatch.setattr(app, "MASTER_KEY_PATH", missing_key)
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(input_csv)])

    with pytest.raises(SystemExit, match="python -m src.generate_key"):
        app.main()
