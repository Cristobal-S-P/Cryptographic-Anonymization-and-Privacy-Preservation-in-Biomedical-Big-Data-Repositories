from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd


class IdentityRepository:
    """Repositorio protegido: no guarda nombre ni RUT en claro."""

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._by_subject: dict[int, dict] = {}
        self._by_pseudonym: dict[str, dict] = {}

    def add(self, row: dict) -> None:
        subject_id = int(row["subject_id"])
        pseudonym = str(row["pseudonym"])
        if subject_id in self._by_subject:
            return
        self._rows.append(row)
        self._by_subject[subject_id] = row
        self._by_pseudonym[pseudonym] = row

    def get_by_subject(self, subject_id: int) -> dict | None:
        return self._by_subject.get(subject_id)

    def get_by_pseudonym(self, pseudonym: str) -> dict | None:
        return self._by_pseudonym.get(pseudonym)

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows)

    def save_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dataframe().to_csv(path, index=False)


class AnalyticalRepository:
    """Repositorio analítico sin nombre, RUT, sales ni secretos."""

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._risk_by_pseudonym: dict[str, bool] = {}
        self._pubkey_by_pseudonym: dict[str, int] = {}

    def add(self, row: dict) -> None:
        self._rows.append(row)
        pseudonym = str(row["pseudonym"])
        previous = self._risk_by_pseudonym.get(pseudonym, False)
        self._risk_by_pseudonym[pseudonym] = previous or bool(row["risk_group"])
        self._pubkey_by_pseudonym[pseudonym] = int(row["schnorr_public_key"])

    def get_risk(self, pseudonym: str) -> bool | None:
        return self._risk_by_pseudonym.get(pseudonym)

    def get_public_key(self, pseudonym: str) -> int | None:
        return self._pubkey_by_pseudonym.get(pseudonym)

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows)

    def save_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dataframe().to_csv(path, index=False)
