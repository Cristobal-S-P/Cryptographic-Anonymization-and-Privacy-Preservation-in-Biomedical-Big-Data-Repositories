from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from .config import DIA_RISK_THRESHOLD, SYS_RISK_THRESHOLD
from .crypto_utils import IdentityCrypto, SimplifiedSchnorr
from .models import PatientCredential
from .repositories import AnalyticalRepository, IdentityRepository


class AnonymizationPipeline:
    """Fragmenta un dataset clínico en repositorio de identidad y analítico."""

    def __init__(
        self,
        crypto: IdentityCrypto,
        identity_repo: IdentityRepository,
        analytical_repo: AnalyticalRepository,
    ) -> None:
        self.crypto = crypto
        self.identity_repo = identity_repo
        self.analytical_repo = analytical_repo
        self._credentials: dict[int, PatientCredential] = {}

    @staticmethod
    def _age_group(age: int) -> str:
        if age < 18:
            return "0-17"
        if age < 40:
            return "18-39"
        if age < 60:
            return "40-59"
        return "60+"

    @staticmethod
    def _is_risk(sys_bp: float, dia_bp: float) -> bool:
        return sys_bp >= SYS_RISK_THRESHOLD or dia_bp >= DIA_RISK_THRESHOLD

    def _register_patient_once(self, row: pd.Series) -> tuple[str, int]:
        subject_id = int(row["subject_id"])
        existing = self.identity_repo.get_by_subject(subject_id)
        if existing:
            return str(existing["pseudonym"]), int(existing["schnorr_public_key"])

        salt = self.crypto.new_salt()
        stretched = self.crypto.stretched_hash(str(row["rut"]), salt)
        # Índice pseudónimo estable para todas las filas del mismo paciente.
        pseudonym = hashlib.sha256(
            f"{subject_id}|{stretched}".encode("utf-8")
        ).hexdigest()

        secret = SimplifiedSchnorr.generate_secret()
        public_key = SimplifiedSchnorr.public_key(secret)
        self._credentials[subject_id] = PatientCredential(pseudonym, secret)

        self.identity_repo.add(
            {
                "subject_id": subject_id,
                "pseudonym": pseudonym,
                "salt_b64": self.crypto.b64(salt),
                "rut_stretched_hash": stretched,
                "nombre_cifrado": self.crypto.encrypt_text(str(row["nombre"])),
                "rut_cifrado": self.crypto.encrypt_text(str(row["rut"])),
                "schnorr_secret_cifrado": self.crypto.encrypt_text(str(secret)),
                "schnorr_public_key": public_key,
            }
        )
        return pseudonym, public_key

    def process(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        for _, row in df.iterrows():
            pseudonym, public_key = self._register_patient_once(row)
            self.analytical_repo.add(
                {
                    "pseudonym": pseudonym,
                    "record_id": int(row["record_id"]),
                    "edad": int(row["edad"]),
                    "age_group": self._age_group(int(row["edad"])),
                    "sexo": str(row["sexo"]),
                    "systolic_bp": float(row["systolic_bp"]),
                    "diastolic_bp": float(row["diastolic_bp"]),
                    "heart_rate": float(row["heart_rate"]),
                    "risk_group": self._is_risk(
                        float(row["systolic_bp"]), float(row["diastolic_bp"])
                    ),
                    "schnorr_public_key": public_key,
                }
            )

        return self.identity_repo.dataframe(), self.analytical_repo.dataframe()

    def credential_for_subject(self, subject_id: int) -> PatientCredential:
        credential = self._credentials.get(subject_id)
        if credential is None:
            row = self.identity_repo.get_by_subject(subject_id)
            if row is None:
                raise KeyError(f"Paciente {subject_id} no registrado.")
            secret = int(self.crypto.decrypt_text(str(row["schnorr_secret_cifrado"])))
            credential = PatientCredential(str(row["pseudonym"]), secret)
        return credential
