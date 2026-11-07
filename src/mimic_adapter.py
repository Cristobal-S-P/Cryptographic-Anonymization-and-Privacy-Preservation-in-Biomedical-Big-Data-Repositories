from __future__ import annotations

from pathlib import Path
from math import isfinite
import re
from typing import Any

import pandas as pd

from .config import (
    AGE_MAX,
    AGE_MIN,
    DIASTOLIC_BP_MAX,
    DIASTOLIC_BP_MIN,
    HEART_RATE_MAX,
    HEART_RATE_MIN,
    SYSTOLIC_BP_MAX,
    SYSTOLIC_BP_MIN,
)


class MimicAdapterError(ValueError):
    pass


class MimicIIIDemoAdapter:
    """Convierte MIMIC-III Demo al esquema clínico tabular del proyecto."""

    REQUIRED_COLUMNS = {
        "PATIENTS.csv": {"SUBJECT_ID", "GENDER", "DOB"},
        "D_ITEMS.csv": {"ITEMID", "LABEL"},
        "CHARTEVENTS.csv": {"SUBJECT_ID", "ITEMID", "CHARTTIME", "VALUENUM"},
    }

    # Se aceptan solo ITEMID documentados. No se combinan presiones invasivas
    # (ABP/arterial) con las mediciones no invasivas.
    ITEM_DEFINITIONS = {
        211: ("heart_rate", {"heartrate"}),
        220045: ("heart_rate", {"heartrate"}),
        455: ("systolic_bp", {"nbpsystolic"}),
        220179: ("systolic_bp", {"noninvasivebloodpressuresystolic"}),
        8441: ("diastolic_bp", {"nbpdiastolic"}),
        220180: ("diastolic_bp", {"noninvasivebloodpressurediastolic"}),
    }

    OUTPUT_COLUMNS = [
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

    def __init__(self, mimic_dir: Path) -> None:
        self.mimic_dir = mimic_dir
        self.patients_path = mimic_dir / "PATIENTS.csv"
        self.items_path = mimic_dir / "D_ITEMS.csv"
        self.chart_path = mimic_dir / "CHARTEVENTS.csv"
        self.last_report: dict[str, int] = {}
        self.record_trace: list[dict[str, Any]] = []

    def _validate_files(self) -> None:
        missing = [
            path.name
            for path in (self.patients_path, self.items_path, self.chart_path)
            if not path.is_file()
        ]
        if missing:
            raise MimicAdapterError(
                "Faltan archivos MIMIC-III Demo: " + ", ".join(missing)
            )
        for filename, required in self.REQUIRED_COLUMNS.items():
            path = self.mimic_dir / filename
            try:
                columns = {str(column).strip().upper() for column in pd.read_csv(path, nrows=0).columns}
            except (OSError, pd.errors.ParserError, UnicodeError) as exc:
                raise MimicAdapterError(f"No se pudo leer el encabezado de {filename}.") from exc
            missing_columns = required.difference(columns)
            if missing_columns:
                raise MimicAdapterError(
                    f"{filename} no contiene las columnas obligatorias: "
                    + ", ".join(sorted(missing_columns))
                )

    @staticmethod
    def _normalize_label(label: object) -> str:
        return re.sub(r"[^a-z0-9]", "", str(label).strip().lower())

    def _discover_itemids(self) -> dict[int, str]:
        try:
            items = pd.read_csv(self.items_path, low_memory=False)
        except (OSError, pd.errors.ParserError, UnicodeError) as exc:
            raise MimicAdapterError("No se pudo leer D_ITEMS.csv.") from exc
        items.columns = [str(column).strip().upper() for column in items.columns]

        mapping: dict[int, str] = {}
        seen_ids: set[int] = set()
        for row in items[["ITEMID", "LABEL"]].dropna().itertuples(index=False):
            try:
                item_value = float(row.ITEMID)
            except (TypeError, ValueError):
                continue
            if not item_value.is_integer():
                continue
            itemid = int(item_value)
            if itemid not in self.ITEM_DEFINITIONS:
                continue
            if itemid in seen_ids:
                raise MimicAdapterError(
                    f"D_ITEMS.csv contiene ITEMID duplicado: {itemid}."
                )
            seen_ids.add(itemid)
            variable, accepted_labels = self.ITEM_DEFINITIONS[itemid]
            if self._normalize_label(row.LABEL) not in accepted_labels:
                raise MimicAdapterError(
                    f"El ITEMID {itemid} tiene una etiqueta inesperada en D_ITEMS.csv; "
                    "se rechaza para evitar asignar una medición clínica incorrecta."
                )
            mapping[itemid] = variable

        missing_variables = {"heart_rate", "systolic_bp", "diastolic_bp"}.difference(
            mapping.values()
        )
        if missing_variables:
            raise MimicAdapterError(
                "D_ITEMS.csv no contiene ITEMID admitidos para: "
                + ", ".join(sorted(missing_variables))
            )
        return mapping

    @staticmethod
    def _fake_rut(subject_id: int) -> str:
        number = 12_000_000 + int(subject_id)
        factors = (2, 3, 4, 5, 6, 7)
        total = sum(
            int(digit) * factors[index % len(factors)]
            for index, digit in enumerate(reversed(str(number)))
        )
        remainder = 11 - total % 11
        check = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)
        return f"{number}-{check}"

    def _patient_metadata(self) -> pd.DataFrame:
        try:
            patients = pd.read_csv(self.patients_path, low_memory=False)
        except (OSError, pd.errors.ParserError, UnicodeError) as exc:
            raise MimicAdapterError("No se pudo leer PATIENTS.csv.") from exc
        patients.columns = [str(column).strip().upper() for column in patients.columns]
        patients = patients[["SUBJECT_ID", "GENDER", "DOB"]].copy()
        patients["SUBJECT_ID"] = pd.to_numeric(
            patients["SUBJECT_ID"], errors="coerce"
        )
        invalid_ids = (
            patients["SUBJECT_ID"].isna()
            | (patients["SUBJECT_ID"] <= 0)
            | (patients["SUBJECT_ID"] % 1 != 0)
        )
        if invalid_ids.any():
            raise MimicAdapterError(
                "PATIENTS.csv contiene SUBJECT_ID vacío o inválido."
            )
        patients["SUBJECT_ID"] = patients["SUBJECT_ID"].astype("int64")
        if patients["SUBJECT_ID"].duplicated().any():
            raise MimicAdapterError("PATIENTS.csv contiene SUBJECT_ID duplicado.")
        patients["DOB"] = pd.to_datetime(
            patients["DOB"], errors="coerce", format="mixed"
        )
        patients["GENDER"] = patients["GENDER"].astype("string").str.strip()
        return patients

    def convert(self, output_csv: Path, max_rows: int | None = None) -> Path:
        self.last_report = {}
        self.record_trace = []
        if max_rows is not None and (
            isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows <= 0
        ):
            raise MimicAdapterError("max_rows debe ser un entero positivo.")

        self._validate_files()
        item_map = self._discover_itemids()
        wanted_ids = set(item_map)
        report = {
            "source_event_rows": 0,
            "unrecognized_item_rows": 0,
            "invalid_event_identifier_rows": 0,
            "missing_valuenum_rows": 0,
            "invalid_valuenum_rows": 0,
            "invalid_charttime_rows": 0,
            "exact_duplicate_measurements": 0,
            "out_of_range_measurement_rows": 0,
            "incomplete_hour_bins": 0,
            "invalid_pressure_order_bins": 0,
            "measurement_bins_without_metadata": 0,
            "subjects_without_metadata": 0,
            "missing_dob_bins": 0,
            "invalid_age_bins": 0,
            "missing_gender_bins": 0,
            "patients_without_recognized_events": 0,
            "patients_without_complete_records": 0,
            "records_truncated_by_max_rows": 0,
            "output_records": 0,
        }
        try:
            patients = self._patient_metadata()
        except (OSError, pd.errors.ParserError, UnicodeError) as exc:
            raise MimicAdapterError("No se pudo leer PATIENTS.csv.") from exc
        patient_ids = set(patients["SUBJECT_ID"])
        event_pieces: list[pd.DataFrame] = []
        required_event_columns = ["SUBJECT_ID", "ITEMID", "CHARTTIME", "VALUENUM"]
        try:
            chunks = pd.read_csv(
                self.chart_path,
                usecols=lambda column: str(column).strip().upper()
                in set(required_event_columns),
                chunksize=150_000,
                low_memory=False,
            )
            for chunk in chunks:
                chunk.columns = [str(column).strip().upper() for column in chunk.columns]
                report["source_event_rows"] += len(chunk)
                chunk["SUBJECT_ID"] = pd.to_numeric(
                    chunk["SUBJECT_ID"], errors="coerce"
                )
                chunk["ITEMID"] = pd.to_numeric(chunk["ITEMID"], errors="coerce")
                invalid_ids = (
                    chunk["SUBJECT_ID"].isna()
                    | chunk["ITEMID"].isna()
                    | (chunk["SUBJECT_ID"] <= 0)
                    | (chunk["SUBJECT_ID"] % 1 != 0)
                    | (chunk["ITEMID"] % 1 != 0)
                )
                report["invalid_event_identifier_rows"] += int(invalid_ids.sum())
                chunk = chunk.loc[~invalid_ids].copy()
                chunk["SUBJECT_ID"] = chunk["SUBJECT_ID"].astype("int64")
                chunk["ITEMID"] = chunk["ITEMID"].astype("int64")

                recognized = chunk["ITEMID"].isin(wanted_ids)
                report["unrecognized_item_rows"] += int((~recognized).sum())
                chunk = chunk.loc[recognized].copy()
                if chunk.empty:
                    continue
                original_values = chunk["VALUENUM"]
                missing_values = original_values.isna() | original_values.map(
                    lambda value: isinstance(value, str) and not value.strip()
                )
                report["missing_valuenum_rows"] += int(missing_values.sum())
                chunk["VALUENUM"] = pd.to_numeric(original_values, errors="coerce")
                invalid_values = (
                    ~missing_values & chunk["VALUENUM"].isna()
                ) | chunk["VALUENUM"].map(
                    lambda value: pd.notna(value) and not isfinite(float(value))
                )
                report["invalid_valuenum_rows"] += int(invalid_values.sum())
                chunk = chunk.loc[~(missing_values | invalid_values)].copy()
                parsed_time = pd.to_datetime(
                    chunk["CHARTTIME"], errors="coerce", format="mixed"
                )
                report["invalid_charttime_rows"] += int(parsed_time.isna().sum())
                chunk["CHARTTIME"] = parsed_time
                chunk = chunk.loc[chunk["CHARTTIME"].notna()].copy()
                if chunk.empty:
                    continue
                chunk["variable"] = chunk["ITEMID"].map(item_map)
                chunk["time_bin"] = chunk["CHARTTIME"].dt.floor("h")
                event_pieces.append(
                    chunk[
                        [
                            "SUBJECT_ID",
                            "ITEMID",
                            "CHARTTIME",
                            "time_bin",
                            "variable",
                            "VALUENUM",
                        ]
                    ]
                )
        except (OSError, ValueError, pd.errors.ParserError, UnicodeError) as exc:
            if isinstance(exc, MimicAdapterError):
                raise
            raise MimicAdapterError(
                "No se pudo leer CHARTEVENTS.csv o faltan sus columnas requeridas."
            ) from exc

        if not event_pieces:
            report["patients_without_recognized_events"] = len(patient_ids)
            self.last_report = report
            raise MimicAdapterError(
                "No hay mediciones válidas de ITEMID admitidos en CHARTEVENTS.csv."
            )

        events = pd.concat(event_pieces, ignore_index=True)
        duplicate_columns = [
            "SUBJECT_ID",
            "ITEMID",
            "CHARTTIME",
            "VALUENUM",
        ]
        duplicate_mask = events.duplicated(duplicate_columns, keep="first")
        report["exact_duplicate_measurements"] = int(duplicate_mask.sum())
        events = events.loc[~duplicate_mask].copy()

        ranges = {
            "heart_rate": (HEART_RATE_MIN, HEART_RATE_MAX),
            "systolic_bp": (SYSTOLIC_BP_MIN, SYSTOLIC_BP_MAX),
            "diastolic_bp": (DIASTOLIC_BP_MIN, DIASTOLIC_BP_MAX),
        }
        valid_ranges = pd.Series(True, index=events.index)
        for variable, (minimum, maximum) in ranges.items():
            values = events["variable"].eq(variable)
            valid_ranges.loc[values] = events.loc[values, "VALUENUM"].between(
                minimum, maximum
            )
        report["out_of_range_measurement_rows"] = int((~valid_ranges).sum())
        events = events.loc[valid_ranges].copy()

        subjects_with_events = set(events["SUBJECT_ID"].unique())
        report["patients_without_recognized_events"] = len(
            patient_ids.difference(subjects_with_events)
        )
        report["subjects_without_metadata"] = len(subjects_with_events.difference(patient_ids))

        events["source_event_count"] = 1
        grouped = (
            events.groupby(
                ["SUBJECT_ID", "time_bin", "variable"], as_index=False, sort=True
            )
            .agg(
                VALUENUM=("VALUENUM", "median"),
                source_event_count=("source_event_count", "sum"),
            )
            .pivot(
                index=["SUBJECT_ID", "time_bin"],
                columns="variable",
                values="VALUENUM",
            )
        )
        counts = events.groupby(["SUBJECT_ID", "time_bin"]).size()
        grouped["source_event_count"] = counts
        grouped = grouped.reset_index()
        measurement_columns = ["heart_rate", "systolic_bp", "diastolic_bp"]
        missing_measurements = grouped[measurement_columns].isna().any(axis=1)
        report["incomplete_hour_bins"] = int(missing_measurements.sum())
        grouped = grouped.loc[~missing_measurements].copy()
        invalid_pressure = grouped["systolic_bp"] <= grouped["diastolic_bp"]
        report["invalid_pressure_order_bins"] = int(invalid_pressure.sum())
        grouped = grouped.loc[~invalid_pressure].copy()

        report["measurement_bins_without_metadata"] = int(
            (~grouped["SUBJECT_ID"].isin(patient_ids)).sum()
        )
        grouped = grouped.merge(
            patients, on="SUBJECT_ID", how="left", validate="many_to_one"
        )
        missing_dob = grouped["DOB"].isna()
        report["missing_dob_bins"] = int(missing_dob.sum())
        grouped["edad"] = (
            (grouped["time_bin"] - grouped["DOB"]).dt.days / 365.2425
        ).round()
        invalid_age = (
            grouped["edad"].notna()
            & ((grouped["edad"] < AGE_MIN) | (grouped["edad"] > AGE_MAX))
        )
        report["invalid_age_bins"] = int(invalid_age.sum())
        missing_gender = grouped["GENDER"].isna() | grouped["GENDER"].eq("")
        report["missing_gender_bins"] = int(missing_gender.sum())
        complete = ~(missing_dob | invalid_age | missing_gender)
        grouped = grouped.loc[complete].copy()
        grouped["edad"] = grouped["edad"].astype(int)
        grouped = grouped.sort_values(["SUBJECT_ID", "time_bin"]).reset_index(drop=True)

        report["patients_without_complete_records"] = len(
            patient_ids.difference(set(grouped["SUBJECT_ID"]))
        )
        if max_rows is not None and len(grouped) > max_rows:
            report["records_truncated_by_max_rows"] = len(grouped) - max_rows
            grouped = grouped.head(max_rows).copy()

        if grouped.empty:
            self.last_report = report
            raise MimicAdapterError(
                "No quedaron registros completos: revise last_report para los "
                "conteos de mediciones incompletas o metadatos faltantes."
            )

        grouped["subject_id"] = grouped["SUBJECT_ID"].astype(int)
        grouped["record_id"] = range(1, len(grouped) + 1)
        grouped["nombre"] = grouped["subject_id"].map(
            lambda subject_id: f"Paciente Simulado MIMIC {subject_id}"
        )
        grouped["rut"] = grouped["subject_id"].map(self._fake_rut)
        grouped["sexo"] = grouped["GENDER"].astype(str)
        result = grouped[
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
        self.record_trace = [
            {
                "record_id": int(row.record_id),
                "subject_id": int(row.subject_id),
                "time_bin": row.time_bin.isoformat(),
                "source_event_count": int(row.source_event_count),
            }
            for row in grouped.itertuples(index=False)
        ]
        report["output_records"] = len(result)
        self.last_report = report

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_csv, index=False)
        return output_csv
