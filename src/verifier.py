from __future__ import annotations

import secrets
from math import isfinite
from threading import Lock
from time import monotonic

from .crypto_utils import SimplifiedSchnorr
from .models import PatientCredential, SchnorrProof
from .repositories import AnalyticalRepository


class AuthorizationError(PermissionError):
    """La prueba no autoriza la consulta clínica solicitada."""


class RiskVerifier:
    """Verifica pruebas de un solo uso dentro de la vida de esta instancia."""

    DEFAULT_NONCE_TTL_SECONDS = 300.0

    def __init__(
        self,
        analytical_repo: AnalyticalRepository,
        nonce_ttl_seconds: float = DEFAULT_NONCE_TTL_SECONDS,
    ) -> None:
        if (
            isinstance(nonce_ttl_seconds, bool)
            or not isinstance(nonce_ttl_seconds, (int, float))
            or not isfinite(nonce_ttl_seconds)
            or nonce_ttl_seconds <= 0
        ):
            raise ValueError("La expiración del nonce debe ser un número positivo.")
        self._repo = analytical_repo
        self._nonce_ttl_seconds = float(nonce_ttl_seconds)
        self._issued_nonces: dict[str, float] = {}
        self._used_nonces: set[str] = set()
        self._nonce_lock = Lock()

    def _expire_nonces(self, now: float) -> None:
        expired = [
            nonce
            for nonce, issued_at in self._issued_nonces.items()
            if now - issued_at >= self._nonce_ttl_seconds
        ]
        for nonce in expired:
            self._issued_nonces.pop(nonce, None)
            self._used_nonces.discard(nonce)

    def new_nonce(self) -> str:
        nonce = secrets.token_hex(SimplifiedSchnorr.NONCE_BYTES)
        with self._nonce_lock:
            self._expire_nonces(monotonic())
            while nonce in self._issued_nonces:
                nonce = secrets.token_hex(SimplifiedSchnorr.NONCE_BYTES)
            self._issued_nonces[nonce] = monotonic()
        return nonce

    def build_proof(
        self,
        credential: PatientCredential,
        nonce: str,
        consultation: str = SimplifiedSchnorr.RISK_QUERY_SCOPE,
    ) -> SchnorrProof:
        return SimplifiedSchnorr.prove(
            pseudonym=credential.pseudonym,
            secret=credential.schnorr_secret,
            nonce=nonce,
            consultation=consultation,
        )

    def verify_proof(
        self, pseudonym: str, proof: SchnorrProof | None, session_nonce: str | None
    ) -> bool:
        if not isinstance(session_nonce, str):
            return False
        with self._nonce_lock:
            now = monotonic()
            self._expire_nonces(now)
            issued_at = self._issued_nonces.get(session_nonce)
            if issued_at is None or session_nonce in self._used_nonces:
                return False
            if now - issued_at >= self._nonce_ttl_seconds:
                self._expire_nonces(now)
                return False
            if not isinstance(proof, SchnorrProof):
                return False
            public_key = self._repo.get_public_key(pseudonym)
            if public_key is None or not SimplifiedSchnorr.verify(
                pseudonym,
                public_key,
                proof,
                expected_nonce=session_nonce,
                consultation=SimplifiedSchnorr.RISK_QUERY_SCOPE,
            ):
                return False
            self._used_nonces.add(session_nonce)
            return True

    def query_risk(
        self,
        pseudonym: str,
        proof: SchnorrProof | None = None,
        session_nonce: str | None = None,
    ) -> bool | None:
        """Lee el riesgo solo si la prueba válida autoriza esta consulta."""
        if not self.verify_proof(pseudonym, proof, session_nonce):
            raise AuthorizationError("Consulta clínica no autorizada.")
        return self._repo.get_risk(pseudonym)
