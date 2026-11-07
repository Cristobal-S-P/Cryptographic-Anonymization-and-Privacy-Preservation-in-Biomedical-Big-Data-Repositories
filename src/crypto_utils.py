from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import PBKDF2_ITERATIONS, SALT_BYTES
from .models import SchnorrProof


class CryptoError(RuntimeError):
    """Error controlado para operaciones criptográficas del proyecto."""


class IdentityCrypto:
    """Hashing con sal + stretching y cifrado reversible de PII."""

    def __init__(self, master_key_path: Path):
        if not master_key_path.is_file():
            raise FileNotFoundError(
                f"No se encontró una clave maestra válida en '{master_key_path}'. "
                "Genérala explícitamente con 'python -m src.generate_key' y "
                "vuelve a ejecutar la aplicación."
            )
        try:
            self._fernet = Fernet(master_key_path.read_bytes().strip())
        except (TypeError, ValueError) as exc:
            raise CryptoError(
                f"La clave maestra en '{master_key_path}' no es válida para "
                "Fernet. No fue modificada. Si no necesitas recuperar datos "
                "cifrados con ella, respáldala fuera de esta ruta antes de "
                "generar una nueva con 'python -m src.generate_key'."
            ) from exc

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
    Prototipo didáctico de prueba Schnorr de conocimiento de una clave.

    Usa el subgrupo de orden primo de 256 bits del grupo MODP de 2048 bits
    definido en RFC 5114, sección 2.3. No es una ZKP formal certificada ni
    una implementación apropiada para producción.

    El desafío c se deriva por Fiat-Shamir de la transcripción y del nonce
    de sesión; el protocolo implementa z = (r + c*x) mod Q y verifica
    G^z = T*Y^c mod P.
    """

    # RFC 5114, grupo 2.3: MODP de 2048 bits, subgrupo primo de 256 bits.
    P = int(
        "87A8E61DB4B6663CFFBBD19C651959998CEEF608660DD0F2"
        "5D2CEED4435E3B00E00DF8F1D61957D4FAF7DF4561B2AA30"
        "16C3D91134096FAA3BF4296D830E9A7C209E0C6497517ABD"
        "5A8A9D306BCF67ED91F9E6725B4758C022E0B1EF4275BF7B"
        "6C5BFC11D45F9088B941F54EB1E59BB8BC39A0BF12307F5C"
        "4FDB70C581B23F76B63ACAE1CAA6B7902D52526735488A0E"
        "F13C6D9A51BFA4AB3AD8347796524D8EF6A167B5A41825D9"
        "67E144E5140564251CCACB83E6B486F6B3CA3F7971506026"
        "C0B857F689962856DED4010ABD0BE621C3A3960A54E710C3"
        "75F26375D7014103A4B54330C198AF126116D2276E11715F"
        "693877FAD7EF09CADB094AE91E1A1597",
        16,
    )
    Q = int(
        "8CF83642A709A097B447997640129DA299B1A47D"
        "1EB3750BA308B0FE64F5FBD3",
        16,
    )
    G = int(
        "3FB32C9B73134D0B2E77506660EDBD484CA7B18F21EF2054"
        "07F4793A1A0BA12510DBC15077BE463FFF4FED4AAC0BB555"
        "BE3A6C1B0C6B47B1BC3773BF7E8C6F62901228F8C28CBB18"
        "A55AE31341000A650196F931C77A57F2DDF463E5E9EC144B"
        "777DE62AAAB8A8628AC376D282D6ED3864E67982428EBC83"
        "1D14348F6F2F9193B5045AF2767164E1DFC967C1FB3F2E55"
        "A4BD1BFFE83B9C80D052B985D182EA0ADB2A3B7313D3FE14"
        "C8484B1E052588B9B7D2BBD2DF016199ECD06E1557CD0915"
        "B3353BBB64E0EC377FD028370DF92B52C7891428CDC67EB6"
        "184B523D1DB246C32F63078490F00EF8D647D148D4795451"
        "5E2327CFEF98C582664B4C0F6CC41659",
        16,
    )
    NONCE_BYTES = 32
    RISK_QUERY_SCOPE = "risk_query"
    _DOMAIN = b"Proyecto7/Schnorr-possession/v2"
    _P_BYTES = (P.bit_length() + 7) // 8
    _Q_BYTES = (Q.bit_length() + 7) // 8

    @classmethod
    def _valid_scalar(cls, value: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value < cls.Q

    @classmethod
    def _valid_response(cls, value: int) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < cls.Q
        )

    @classmethod
    def _valid_group_element(cls, value: int) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 < value < cls.P
            and pow(value, cls.Q, cls.P) == 1
        )

    @classmethod
    def _valid_nonce(cls, nonce: str) -> bool:
        return (
            isinstance(nonce, str)
            and len(nonce) == cls.NONCE_BYTES * 2
            and all(character in "0123456789abcdef" for character in nonce)
        )

    @staticmethod
    def _valid_consultation(consultation: str) -> bool:
        return (
            isinstance(consultation, str)
            and bool(consultation)
            and len(consultation.encode("utf-8")) < 2**32
        )

    @classmethod
    def generate_secret(cls) -> int:
        return secrets.randbelow(cls.Q - 1) + 1

    @classmethod
    def public_key(cls, secret: int) -> int:
        if not cls._valid_scalar(secret):
            raise ValueError("El secreto Schnorr está fuera del rango permitido.")
        return pow(cls.G, secret, cls.P)

    @classmethod
    def _challenge(
        cls,
        pseudonym: str,
        public_key: int,
        commitment: int,
        nonce: str,
        consultation: str,
    ) -> int:
        pseudonym_bytes = pseudonym.encode("utf-8")
        consultation_bytes = consultation.encode("utf-8")
        material = (
            cls._DOMAIN
            + len(pseudonym_bytes).to_bytes(4, "big")
            + pseudonym_bytes
            + public_key.to_bytes(cls._P_BYTES, "big")
            + commitment.to_bytes(cls._P_BYTES, "big")
            + bytes.fromhex(nonce)
            + len(consultation_bytes).to_bytes(4, "big")
            + consultation_bytes
        )
        return int.from_bytes(hashlib.sha256(material).digest(), "big") % cls.Q

    @classmethod
    def prove(
        cls,
        pseudonym: str,
        secret: int,
        nonce: str,
        consultation: str = RISK_QUERY_SCOPE,
    ) -> SchnorrProof:
        if not isinstance(pseudonym, str) or not pseudonym:
            raise ValueError("El pseudónimo debe ser texto no vacío.")
        if not cls._valid_scalar(secret):
            raise ValueError("El secreto Schnorr está fuera del rango permitido.")
        if not cls._valid_nonce(nonce):
            raise ValueError("El nonce debe contener 32 bytes aleatorios en hexadecimal.")
        if not cls._valid_consultation(consultation):
            raise ValueError("La consulta debe ser texto no vacío.")

        r = secrets.randbelow(cls.Q - 1) + 1
        commitment = pow(cls.G, r, cls.P)
        public_key = cls.public_key(secret)
        c = cls._challenge(pseudonym, public_key, commitment, nonce, consultation)
        response = (r + c * secret) % cls.Q
        return SchnorrProof(commitment=commitment, response=response, nonce=nonce)

    @classmethod
    def verify(
        cls,
        pseudonym: str,
        public_key: int,
        proof: SchnorrProof,
        expected_nonce: str,
        consultation: str = RISK_QUERY_SCOPE,
    ) -> bool:
        if not isinstance(pseudonym, str) or not pseudonym:
            return False
        if not cls._valid_nonce(expected_nonce) or not isinstance(proof, SchnorrProof):
            return False
        if not cls._valid_consultation(consultation):
            return False
        if proof.nonce != expected_nonce:
            return False
        if not cls._valid_group_element(public_key):
            return False
        if not cls._valid_group_element(proof.commitment):
            return False
        if not cls._valid_response(proof.response):
            return False

        c = cls._challenge(
            pseudonym, public_key, proof.commitment, expected_nonce, consultation
        )
        left = pow(cls.G, proof.response, cls.P)
        right = (proof.commitment * pow(public_key, c, cls.P)) % cls.P
        return hmac.compare_digest(
            left.to_bytes(cls._P_BYTES, "big"),
            right.to_bytes(cls._P_BYTES, "big"),
        )
