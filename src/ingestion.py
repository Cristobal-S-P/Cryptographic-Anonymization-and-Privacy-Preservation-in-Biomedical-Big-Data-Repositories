from __future__ import annotations

import csv
import math
import re
from pathlib import Path

import pandas as pd

from .config import (
    AGE_MAX,
    AGE_MIN,
    DIASTOLIC_BP_MAX,
    DIASTOLIC_BP_MIN,
    HEART_RATE_MAX,
    HEART_RATE_MIN,
    REQUIRED_COLUMNS,
    SYSTOLIC_BP_MAX,
    SYSTOLIC_BP_MIN,
)

_NUMERIC_COLUMNS = (
    "subject_id",
    "record_id",
    "edad",
    "systolic_bp",
    "diastolic_bp",
    "heart_rate",
)
_TEXT_COLUMNS = ("nombre", "rut", "sexo")
_RUT_PATTERN = re.compile(r"(?:\d{1,2}(?:\.\d{3}){1,2}|\d{1,8})-?[\dKk]\Z")
_MAX_REPORTED_ROWS = 20


class IngestionError(ValueError):
    pass


class ClinicalCSVLoader:
    @staticmethod
    def _format_rows(rows: list[int]) -> str:
        shown = ", ".join(str(row) for row in rows[:_MAX_REPORTED_ROWS])
        remaining = len(rows) - _MAX_REPORTED_ROWS
        if remaining > 0:
            shown += f", ... ({remaining} filas adicionales)"
        return shown

    @staticmethod
    def _valid_chilean_rut(value: str) -> bool:
        rut = value.strip().upper()
        if not _RUT_PATTERN.fullmatch(rut):
            return False

        body, check_digit = rut.replace(".", "").replace("-", "")[:-1], rut[-1]
        factors = (2, 3, 4, 5, 6, 7)
        total = sum(
            int(digit) * factors[index % len(factors)]
            for index, digit in enumerate(reversed(body))
        )
        remainder = 11 - total % 11
        expected = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)
        return check_digit == expected

    @staticmethod
    def load(path: Path) -> pd.DataFrame:
        if not path.exists():
            raise IngestionError(f"No existe el archivo de entrada: {path}")

        try:
            with path.open(encoding="utf-8-sig", newline="") as csv_file:
                header = next(csv.reader(csv_file), None)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise IngestionError(f"No se pudo leer el CSV de entrada: {path}") from exc
        if not header:
            raise IngestionError("El CSV está vacío o no contiene encabezados.")
        if len(header) != len(set(header)):
            duplicates = sorted(
                {column for column in header if header.count(column) > 1}
            )
            raise IngestionError(
                "Hay nombres de columnas duplicados: " + ", ".join(duplicates)
            )

        try:
            df = pd.read_csv(
                path,
                dtype={column: "string" for column in _TEXT_COLUMNS},
                skip_blank_lines=False,
            )
        except pd.errors.EmptyDataError as exc:
            raise IngestionError("El CSV está vacío.") from exc
        except (pd.errors.ParserError, UnicodeError) as exc:
            raise IngestionError("El archivo no contiene un CSV válido.") from exc

        missing = REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise IngestionError(
                "Faltan columnas obligatorias: " + ", ".join(sorted(missing))
            )

        if df.empty:
            raise IngestionError("El CSV está vacío.")

        errors: list[str] = []
        row_numbers = pd.Series(range(2, len(df) + 2), index=df.index)
        blank_rows = row_numbers[df.isna().all(axis=1)].tolist()
        if blank_rows:
            errors.append(
                "Filas completamente vacías: " + ClinicalCSVLoader._format_rows(blank_rows)
            )

        for column in sorted(REQUIRED_COLUMNS):
            values = df[column]
            missing_values = values.isna() | values.map(
                lambda value: isinstance(value, str) and not value.strip()
            )
            rows = row_numbers[missing_values].tolist()
            if rows:
                errors.append(
                    f"Campo obligatorio '{column}' vacío o nulo en filas: "
                    f"{ClinicalCSVLoader._format_rows(rows)}"
                )

        for column in _TEXT_COLUMNS:
            invalid_type = ~df[column].map(lambda value: isinstance(value, str))
            rows = row_numbers[invalid_type].tolist()
            if rows:
                errors.append(
                    f"El campo '{column}' debe ser texto en filas: "
                    f"{ClinicalCSVLoader._format_rows(rows)}"
                )

        for column in _NUMERIC_COLUMNS:
            original = df[column]
            converted = pd.to_numeric(original, errors="coerce")
            invalid = (converted.isna() & ~original.isna()) | converted.map(
                lambda value: pd.notna(value) and not math.isfinite(value)
            )
            rows = row_numbers[invalid].tolist()
            if rows:
                errors.append(
                    f"El campo '{column}' debe ser numérico en filas: "
                    f"{ClinicalCSVLoader._format_rows(rows)}"
                )
            df[column] = converted

        if errors:
            raise IngestionError("Errores de validación:\n- " + "\n- ".join(errors))

        for column in ("subject_id", "record_id", "edad"):
            values = df[column]
            invalid = (values % 1 != 0) | (values < 0)
            if column in ("subject_id", "record_id"):
                invalid |= values == 0
            rows = row_numbers[invalid].tolist()
            if rows:
                label = "entero positivo" if column != "edad" else "edad entera"
                errors.append(
                    f"El campo '{column}' debe ser {label} en filas: "
                    f"{ClinicalCSVLoader._format_rows(rows)}"
                )

        duplicate_records = df["record_id"].duplicated(keep=False)
        rows = row_numbers[duplicate_records].tolist()
        if rows:
            errors.append(
                "Valores duplicados en 'record_id' en filas: "
                + ClinicalCSVLoader._format_rows(rows)
            )

        for column in ("nombre", "rut"):
            if column == "nombre":
                normalized = df[column].str.strip()
            else:
                normalized = df[column].map(
                    lambda value: "".join(value.upper().split())
                    .replace(".", "")
                    .replace("-", "")
                )
                valid_rut = df[column].map(ClinicalCSVLoader._valid_chilean_rut)
                rows = row_numbers[~valid_rut].tolist()
                if rows:
                    errors.append(
                        "RUT chileno inválido (formato o dígito verificador) en filas: "
                        + ClinicalCSVLoader._format_rows(rows)
                    )

            distinct_values = normalized.groupby(df["subject_id"]).nunique()
            inconsistent_subjects = distinct_values[distinct_values > 1].index
            if len(inconsistent_subjects):
                rows = row_numbers[df["subject_id"].isin(inconsistent_subjects)].tolist()
                errors.append(
                    f"El campo '{column}' es inconsistente para un mismo "
                    f"'subject_id' en filas: {ClinicalCSVLoader._format_rows(rows)}"
                )

        ranges = {
            "edad": (AGE_MIN, AGE_MAX),
            "systolic_bp": (SYSTOLIC_BP_MIN, SYSTOLIC_BP_MAX),
            "diastolic_bp": (DIASTOLIC_BP_MIN, DIASTOLIC_BP_MAX),
            "heart_rate": (HEART_RATE_MIN, HEART_RATE_MAX),
        }
        for column, (minimum, maximum) in ranges.items():
            invalid = (df[column] < minimum) | (df[column] > maximum)
            rows = row_numbers[invalid].tolist()
            if rows:
                errors.append(
                    f"El campo '{column}' está fuera del rango técnico "
                    f"{minimum}–{maximum} en filas: "
                    f"{ClinicalCSVLoader._format_rows(rows)}"
                )

        invalid_pressure = df["systolic_bp"] <= df["diastolic_bp"]
        rows = row_numbers[invalid_pressure].tolist()
        if rows:
            errors.append(
                "La presión sistólica debe ser mayor que la diastólica "
                "en filas: " + ClinicalCSVLoader._format_rows(rows)
            )

        if errors:
            raise IngestionError("Errores de validación:\n- " + "\n- ".join(errors))

        return df
