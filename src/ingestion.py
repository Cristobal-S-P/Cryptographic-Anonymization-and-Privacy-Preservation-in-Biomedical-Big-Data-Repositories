from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import REQUIRED_COLUMNS


class IngestionError(ValueError):
    pass


class ClinicalCSVLoader:
    @staticmethod
    def load(path: Path) -> pd.DataFrame:
        if not path.exists():
            raise IngestionError(f"No existe el archivo de entrada: {path}")

        df = pd.read_csv(path)
        missing = REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise IngestionError(
                "Faltan columnas obligatorias: " + ", ".join(sorted(missing))
            )

        if df.empty:
            raise IngestionError("El CSV está vacío.")

        numeric = ["subject_id", "record_id", "edad", "systolic_bp", "diastolic_bp", "heart_rate"]
        for column in numeric:
            df[column] = pd.to_numeric(df[column], errors="raise")

        if (df["systolic_bp"] <= 0).any() or (df["diastolic_bp"] <= 0).any():
            raise IngestionError("Las presiones deben ser mayores que cero.")
        if (df["systolic_bp"] <= df["diastolic_bp"]).any():
            raise IngestionError("Se detectó presión sistólica <= diastólica.")
        if ((df["heart_rate"] < 20) | (df["heart_rate"] > 250)).any():
            raise IngestionError("Se detectó frecuencia cardíaca fuera del rango de validación.")
        if ((df["edad"] < 0) | (df["edad"] > 120)).any():
            raise IngestionError("Se detectó edad fuera del rango de validación.")

        return df
