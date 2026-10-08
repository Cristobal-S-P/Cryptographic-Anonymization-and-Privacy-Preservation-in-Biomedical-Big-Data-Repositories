from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


class MimicAdapterError(ValueError):
    pass


class MimicIIIDemoAdapter:
    """
    Convierte tablas MIMIC-III Demo a un CSV tabular usado por el pipeline.

    Lee PATIENTS.csv, D_ITEMS.csv y CHARTEVENTS.csv. Los ITEMID se descubren
    desde las etiquetas de D_ITEMS para no depender exclusivamente de números
    codificados a mano.
    """

    HR_PATTERNS = ("heart rate",)
    SYS_PATTERNS = ("systolic", "nbp systolic", "arterial bp systolic")
    DIA_PATTERNS = ("diastolic", "nbp diastolic", "arterial bp diastolic")

    def __init__(self, mimic_dir: Path) -> None:
        self.mimic_dir = mimic_dir
        self.patients_path = mimic_dir / "PATIENTS.csv"
        self.items_path = mimic_dir / "D_ITEMS.csv"
        self.chart_path = mimic_dir / "CHARTEVENTS.csv"

    def _validate_files(self) -> None:
        missing = [p.name for p in (self.patients_path, self.items_path, self.chart_path) if not p.exists()]
        if missing:
            raise MimicAdapterError(
                "Faltan archivos MIMIC-III Demo: " + ", ".join(missing)
            )

    @staticmethod
    def _contains_any(label: str, patterns: tuple[str, ...]) -> bool:
        text = str(label).strip().lower()
        return any(pattern in text for pattern in patterns)

    def _discover_itemids(self) -> dict[int, str]:
        items = pd.read_csv(self.items_path, low_memory=False)
        items.columns = [c.upper() for c in items.columns]
        if not {"ITEMID", "LABEL"}.issubset(items.columns):
            raise MimicAdapterError("D_ITEMS.csv no contiene ITEMID y LABEL.")

        mapping: dict[int, str] = {}
        for _, row in items[["ITEMID", "LABEL"]].dropna().iterrows():
            itemid = int(row["ITEMID"])
            label = str(row["LABEL"])
            if self._contains_any(label, self.HR_PATTERNS):
                mapping[itemid] = "heart_rate"
            elif self._contains_any(label, self.SYS_PATTERNS):
                mapping[itemid] = "systolic_bp"
            elif self._contains_any(label, self.DIA_PATTERNS):
                mapping[itemid] = "diastolic_bp"

        if not {"heart_rate", "systolic_bp", "diastolic_bp"}.issubset(set(mapping.values())):
            raise MimicAdapterError(
                "No fue posible identificar las tres variables (FC, PAS y PAD) en D_ITEMS.csv."
            )
        return mapping

    @staticmethod
    def _fake_rut(subject_id: int) -> str:
        number = 12_000_000 + int(subject_id)
        factors = [2, 3, 4, 5, 6, 7]
        total = sum(
            int(d) * factors[i % 6]
            for i, d in enumerate(reversed(str(number)))
        )
        dv = 11 - total % 11
        check = "0" if dv == 11 else "K" if dv == 10 else str(dv)
        return f"{number}-{check}"

    def _patient_metadata(self) -> pd.DataFrame:
        patients = pd.read_csv(self.patients_path)
        patients.columns = [c.upper() for c in patients.columns]
        required = {"SUBJECT_ID", "GENDER", "DOB"}
        if not required.issubset(patients.columns):
            raise MimicAdapterError("PATIENTS.csv no contiene SUBJECT_ID, GENDER y DOB.")

        patients["DOB"] = pd.to_datetime(patients["DOB"], errors="coerce")
        # MIMIC desplaza fechas por desidentificación. Para esta demo se usa una
        # edad aproximada a partir de la primera medición disponible más adelante.
        return patients[["SUBJECT_ID", "GENDER", "DOB"]]

    def convert(self, output_csv: Path, max_rows: int | None = None) -> Path:
        self._validate_files()
        item_map = self._discover_itemids()
        wanted_ids = set(item_map)

        pieces: list[pd.DataFrame] = []
        usecols = ["SUBJECT_ID", "ITEMID", "CHARTTIME", "VALUENUM"]
        for chunk in pd.read_csv(
            self.chart_path,
            usecols=usecols,
            chunksize=150_000,
            low_memory=False,
        ):
            chunk = chunk[chunk["ITEMID"].isin(wanted_ids)].copy()
            chunk = chunk.dropna(subset=["SUBJECT_ID", "CHARTTIME", "VALUENUM"])
            if chunk.empty:
                continue
            chunk["variable"] = chunk["ITEMID"].map(item_map)
            chunk["CHARTTIME"] = pd.to_datetime(chunk["CHARTTIME"], errors="coerce")
            chunk = chunk.dropna(subset=["CHARTTIME"])
            # Agrupar por hora aumenta la probabilidad de tener PAS/PAD/FC del mismo episodio.
            chunk["time_bin"] = chunk["CHARTTIME"].dt.floor("h")
            pieces.append(chunk[["SUBJECT_ID", "time_bin", "variable", "VALUENUM"]])

        if not pieces:
            raise MimicAdapterError("No se encontraron mediciones compatibles en CHARTEVENTS.csv.")

        events = pd.concat(pieces, ignore_index=True)
        grouped = (
            events.groupby(["SUBJECT_ID", "time_bin", "variable"], as_index=False)["VALUENUM"]
            .median()
            .pivot(index=["SUBJECT_ID", "time_bin"], columns="variable", values="VALUENUM")
            .reset_index()
        )
        grouped = grouped.dropna(subset=["heart_rate", "systolic_bp", "diastolic_bp"])
        grouped = grouped[
            (grouped["systolic_bp"] > grouped["diastolic_bp"])
            & grouped["systolic_bp"].between(50, 260)
            & grouped["diastolic_bp"].between(20, 180)
            & grouped["heart_rate"].between(20, 250)
        ].copy()

        patients = self._patient_metadata()
        out = grouped.merge(patients, on="SUBJECT_ID", how="left")
        out["DOB"] = pd.to_datetime(out["DOB"], errors="coerce")
        out["edad"] = ((out["time_bin"] - out["DOB"]).dt.days / 365.2425).round().fillna(50)
        # En MIMIC, edades muy avanzadas pueden aparecer desplazadas por protección de identidad.
        out.loc[(out["edad"] < 0) | (out["edad"] > 120), "edad"] = 90
        out["edad"] = out["edad"].astype(int)
        out["sexo"] = out["GENDER"].fillna("U").astype(str)
        out["subject_id"] = out["SUBJECT_ID"].astype(int)
        out["record_id"] = range(1, len(out) + 1)
        out["nombre"] = out["subject_id"].map(lambda x: f"Paciente Simulado MIMIC {x}")
        out["rut"] = out["subject_id"].map(self._fake_rut)

        result = out[
            [
                "subject_id",
                "record_id",
                "nombre",
                "rut",
                "edad",
                "sexo",
                "systolic_bp",
                "diastolic_bp",
                "heart_rate",
            ]
        ].copy()

        if max_rows is not None:
            result = result.head(max_rows)
        if result.empty:
            raise MimicAdapterError(
                "No quedaron filas completas después de combinar FC, PAS y PAD por hora."
            )

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_csv, index=False)
        return output_csv
