from __future__ import annotations

import secrets

from .crypto_utils import SimplifiedSchnorr
from .models import PatientCredential, SchnorrProof
from .repositories import AnalyticalRepository


class RiskVerifier:
    """Verifica prueba pseudónima y devuelve solo pertenencia a cohorte."""

    def __init__(self, analytical_repo: AnalyticalRepository) -> None:
        self._repo = analytical_repo

    @staticmethod
    def new_nonce() -> str:
        return secrets.token_hex(16)

    def build_proof(self, credential: PatientCredential, nonce: str) -> SchnorrProof:
        return SimplifiedSchnorr.prove(
            pseudonym=credential.pseudonym,
            secret=credential.schnorr_secret,
            nonce=nonce,
        )

    def verify_and_query(self, pseudonym: str, proof: SchnorrProof) -> bool:
        public_key = self._repo.get_public_key(pseudonym)
        if public_key is None:
            return False
        if not SimplifiedSchnorr.verify(pseudonym, public_key, proof):
            return False
        risk = self._repo.get_risk(pseudonym)
        return bool(risk)
