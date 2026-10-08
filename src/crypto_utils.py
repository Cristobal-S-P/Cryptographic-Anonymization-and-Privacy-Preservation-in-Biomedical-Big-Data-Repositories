from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import PBKDF2_ITERATIONS, SALT_BYTES
from .models import SchnorrProof


class CryptoError(RuntimeError):
    """Error controlado para operaciones criptográficas del proyecto."""


@dataclass(frozen=True)
class SchnorrPublicData:
    public_key: int


class IdentityCrypto:
    """Hashing con sal + stretching y cifrado reversible de PII."""

    def __init__(self, master_key_path: Path):
        master_key_path.parent.mkdir(parents=True, exist_ok=True)
        if not master_key_path.exists():
            master_key_path.write_bytes(Fernet.generate_key())
        self._fernet = Fernet(master_key_path.read_bytes().strip())

    @staticmethod
    def normalize_rut(rut: str) -> str:
        return rut.replace(".", "").replace("-", "").strip().upper()

    @staticmethod
    def new_salt() -> bytes:
        return os.urandom(SALT_BYTES)

    @staticmethod
    def stretched_hash(identifier: str, salt: bytes) -> str:
        normalized = IdentityCrypto.normalize_rut(identifier).encode("utf-8")
        digest = hashlib.pbkdf2_hmac(
            "sha256", normalized, salt, PBKDF2_ITERATIONS, dklen=32
        )
        return digest.hex()

    @staticmethod
    def constant_time_equal(a: str, b: str) -> bool:
        return hmac.compare_digest(a, b)

    def encrypt_text(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt_text(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise CryptoError("No fue posible descifrar el dato protegido.") from exc

    @staticmethod
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii")

    @staticmethod
    def unb64(data: str) -> bytes:
        return base64.urlsafe_b64decode(data.encode("ascii"))


class SimplifiedSchnorr:
    """
    Prueba de conocimiento cero simplificada (Schnorr).

    Demuestra conocimiento de un secreto asociado a un pseudónimo sin enviar
    el secreto ni PII. Es una demostración académica, no una implementación
    certificada para uso clínico real.
    """

    # Grupo MODP pequeño para fines didácticos. No usar en producción.
    P = 2**127 - 1
    G = 3
    Q = P - 1

    @classmethod
    def generate_secret(cls) -> int:
        return secrets.randbelow(cls.Q - 2) + 2

    @classmethod
    def public_key(cls, secret: int) -> int:
        return pow(cls.G, secret, cls.P)

    @classmethod
    def _challenge(cls, pseudonym: str, public_key: int, commitment: int, nonce: str) -> int:
        material = f"{pseudonym}|{public_key}|{commitment}|{nonce}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(material).digest(), "big") % cls.Q

    @classmethod
    def prove(cls, pseudonym: str, secret: int, nonce: str) -> SchnorrProof:
        r = secrets.randbelow(cls.Q - 2) + 2
        commitment = pow(cls.G, r, cls.P)
        c = cls._challenge(pseudonym, cls.public_key(secret), commitment, nonce)
        response = (r + c * secret) % cls.Q
        return SchnorrProof(commitment=commitment, response=response, nonce=nonce)

    @classmethod
    def verify(cls, pseudonym: str, public_key: int, proof: SchnorrProof) -> bool:
        c = cls._challenge(pseudonym, public_key, proof.commitment, proof.nonce)
        left = pow(cls.G, proof.response, cls.P)
        right = (proof.commitment * pow(public_key, c, cls.P)) % cls.P
        return hmac.compare_digest(str(left), str(right))
