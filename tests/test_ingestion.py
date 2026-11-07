from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.ingestion import ClinicalCSVLoader, IngestionError
from src.sample_data import generate


VALID_ROW = {
    "subject_id": 1,
    "record_id": 1,
    "nombre": "Paciente Sintético",
    "rut": "12.345.678-5",
    "edad": 42,
    "sexo": "F",
    "systolic_bp": 120,
    "diastolic_bp": 80,
    "heart_rate": 72,
}
FIELDS = list(VALID_ROW)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _valid_rows() -> list[dict[str, object]]:
    return [VALID_ROW.copy()]


def test_loads_valid_csv_and_preserves_columns(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "valid.csv", _valid_rows())

    result = ClinicalCSVLoader.load(path)

    assert list(result.columns) == FIELDS
    assert len(result) == 1
    assert result.loc[0, "rut"] == VALID_ROW["rut"]


def test_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(IngestionError, match="vacío"):
        ClinicalCSVLoader.load(path)


def test_rejects_missing_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS[:-1])
        writer.writeheader()
        writer.writerow({field: VALID_ROW[field] for field in FIELDS[:-1]})

    with pytest.raises(IngestionError, match="Faltan columnas.*heart_rate"):
        ClinicalCSVLoader.load(path)


def test_rejects_duplicate_column_names(tmp_path: Path) -> None:
    path = tmp_path / "duplicate_columns.csv"
    path.write_text(
        "subject_id,record_id,nombre,rut,edad,sexo,systolic_bp,"
        "diastolic_bp,heart_rate,edad\n"
        "1,1,Paciente Sintético,12345678-5,42,F,120,80,72,42\n",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="columnas duplicados.*edad"):
        ClinicalCSVLoader.load(path)


def test_rejects_completely_blank_rows_and_reports_row(tmp_path: Path) -> None:
    path = tmp_path / "blank_row.csv"
    path.write_text(
        ",".join(FIELDS) + "\n"
        + ",".join(str(VALID_ROW[field]) for field in FIELDS)
        + "\n,,,,,,,,\n",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="Filas completamente vacías: 3"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("rut", ""), ("nombre", "   "), ("sexo", "")],
)
def test_rejects_blank_required_values(
    tmp_path: Path, field: str, value: str
) -> None:
    row = VALID_ROW.copy()
    row[field] = value
    path = _write_csv(tmp_path / "blank_value.csv", [row])

    with pytest.raises(IngestionError, match=field):
        ClinicalCSVLoader.load(path)


def test_rejects_null_required_value(tmp_path: Path) -> None:
    path = tmp_path / "null.csv"
    path.write_text(
        ",".join(FIELDS) + "\n1,1,Paciente Sintético,12345678-5,42,F,120,80,\n",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="heart_rate.*vacío o nulo.*fila"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize(
    "field",
    [
        "subject_id",
        "record_id",
        "edad",
        "systolic_bp",
        "diastolic_bp",
        "heart_rate",
    ],
)
def test_rejects_non_numeric_clinical_values(
    tmp_path: Path, field: str
) -> None:
    row = VALID_ROW.copy()
    row[field] = "desconocido"
    path = _write_csv(tmp_path / "nonnumeric.csv", [row])

    with pytest.raises(IngestionError, match=f"{field}.*numérico"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize("field", ["subject_id", "record_id"])
def test_rejects_non_integer_identifiers(tmp_path: Path, field: str) -> None:
    row = VALID_ROW.copy()
    row[field] = 1.5
    path = _write_csv(tmp_path / "fractional_id.csv", [row])

    with pytest.raises(IngestionError, match=f"{field}.*entero positivo.*fila"):
        ClinicalCSVLoader.load(path)


def test_rejects_non_finite_numeric_values(tmp_path: Path) -> None:
    row = VALID_ROW.copy()
    row["subject_id"] = float("inf")
    path = _write_csv(tmp_path / "infinite_id.csv", [row])

    with pytest.raises(IngestionError, match="subject_id.*numérico"):
        ClinicalCSVLoader.load(path)


def test_rejects_duplicate_record_id_and_reports_rows(tmp_path: Path) -> None:
    first = VALID_ROW.copy()
    second = VALID_ROW.copy()
    second.update(subject_id=2, record_id=1, nombre="Otra Paciente", rut="10.000.000-8")
    path = _write_csv(tmp_path / "duplicate_record.csv", [first, second])

    with pytest.raises(IngestionError, match="record_id.*filas: 2, 3"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize(
    ("field", "second_value"),
    [("nombre", "Paciente Distinto"), ("rut", "10.000.000-8")],
)
def test_rejects_patient_identity_inconsistency(
    tmp_path: Path, field: str, second_value: str
) -> None:
    first = VALID_ROW.copy()
    second = VALID_ROW.copy()
    second.update(record_id=2)
    second[field] = second_value
    path = _write_csv(tmp_path / f"inconsistent_{field}.csv", [first, second])

    with pytest.raises(IngestionError, match=f"{field}.*subject_id.*filas: 2, 3"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize("rut", ["12345678-5", "12.345.6785", "123456785", "11111111-1"])
def test_accepts_valid_chilean_rut_formats(tmp_path: Path, rut: str) -> None:
    row = VALID_ROW.copy()
    row["rut"] = rut
    path = _write_csv(tmp_path / "valid_rut.csv", [row])

    assert ClinicalCSVLoader.load(path).loc[0, "rut"] == rut


@pytest.mark.parametrize("rut", ["12.345.678-6", "12345678-X", "12.34.567-8"])
def test_rejects_invalid_chilean_rut(tmp_path: Path, rut: str) -> None:
    row = VALID_ROW.copy()
    row["rut"] = rut
    path = _write_csv(tmp_path / "invalid_rut.csv", [row])

    with pytest.raises(IngestionError, match="RUT chileno inválido.*filas: 2"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("edad", -1),
        ("edad", 121),
        ("systolic_bp", 49),
        ("systolic_bp", 261),
        ("diastolic_bp", 19),
        ("diastolic_bp", 181),
        ("heart_rate", 19),
        ("heart_rate", 251),
    ],
)
def test_rejects_values_outside_technical_clinical_ranges(
    tmp_path: Path, field: str, value: int
) -> None:
    row = VALID_ROW.copy()
    row[field] = value
    path = _write_csv(tmp_path / "out_of_range.csv", [row])

    with pytest.raises(IngestionError, match=f"{field}.*rango técnico.*fila"):
        ClinicalCSVLoader.load(path)


@pytest.mark.parametrize("diastolic", [120, 130])
def test_requires_systolic_pressure_strictly_greater_than_diastolic(
    tmp_path: Path, diastolic: int
) -> None:
    row = VALID_ROW.copy()
    row.update(systolic_bp=diastolic, diastolic_bp=diastolic)
    path = _write_csv(tmp_path / "pressure_order.csv", [row])

    with pytest.raises(IngestionError, match="sistólica debe ser mayor"):
        ClinicalCSVLoader.load(path)


def test_accepts_100_record_synthetic_dataset(tmp_path: Path) -> None:
    path = generate(
        tmp_path / "clinical_demo.csv",
        patients=20,
        records_per_patient=5,
    )
    result = ClinicalCSVLoader.load(path)

    assert len(result) == 100
    assert result["subject_id"].nunique() == 20


def test_accepts_1000_record_synthetic_dataset(tmp_path: Path) -> None:
    path = generate(
        tmp_path / "clinical_demo_200_pacientes_5_registros.csv",
        patients=200,
        records_per_patient=5,
    )
    result = ClinicalCSVLoader.load(path)

    assert len(result) == 1000
    assert result["subject_id"].nunique() == 200


def test_different_subjects_are_not_merged_by_shared_identity_values(
    tmp_path: Path,
) -> None:
    first = VALID_ROW.copy()
    second = VALID_ROW.copy()
    second.update(subject_id=2, record_id=2)
    path = _write_csv(tmp_path / "different_subjects.csv", [first, second])

    result = ClinicalCSVLoader.load(path)
    assert len(result) == 2
    assert result["subject_id"].nunique() == 2
