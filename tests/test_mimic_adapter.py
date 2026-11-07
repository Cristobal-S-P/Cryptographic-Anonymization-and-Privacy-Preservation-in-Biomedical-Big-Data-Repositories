from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.crypto_utils import IdentityCrypto
from src.generate_key import generate_master_key
from src.ingestion import ClinicalCSVLoader
from src.mimic_adapter import MimicAdapterError, MimicIIIDemoAdapter
from src.pipeline import AnonymizationPipeline
from src.repositories import AnalyticalRepository, IdentityRepository


ITEMS = [
    (211, "Heart Rate"),
    (220045, "Heart Rate"),
    (455, "NBP [Systolic]"),
    (220179, "Non Invasive Blood Pressure systolic"),
    (8441, "NBP [Diastolic]"),
    (220180, "Non Invasive Blood Pressure diastolic"),
    (51, "Arterial Blood Pressure systolic"),
    (442, "Manual Blood Pressure systolic"),
    (220050, "Arterial Blood Pressure systolic"),
    (9999, "Unrelated measurement"),
]


def _write_mimic(
    directory: Path,
    *,
    patients: list[dict] | None = None,
    items: list[tuple[int, str]] | None = None,
    events: list[dict] | None = None,
    patient_columns: list[str] | None = None,
    item_columns: list[str] | None = None,
    event_columns: list[str] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if patients is not None or patient_columns is not None:
        pd.DataFrame(
            patients or [],
            columns=patient_columns or ["SUBJECT_ID", "GENDER", "DOB"],
        ).to_csv(directory / "PATIENTS.csv", index=False)
    if items is not None or item_columns is not None:
        pd.DataFrame(
            items or [], columns=item_columns or ["ITEMID", "LABEL"]
        ).to_csv(directory / "D_ITEMS.csv", index=False)
    if events is not None or event_columns is not None:
        pd.DataFrame(
            events or [],
            columns=event_columns
            or ["SUBJECT_ID", "ITEMID", "CHARTTIME", "VALUENUM"],
        ).to_csv(directory / "CHARTEVENTS.csv", index=False)
    return directory


def _valid_fixture(directory: Path) -> Path:
    patients = [
        {"SUBJECT_ID": 10, "GENDER": "F", "DOB": "1980-01-01"},
        {"SUBJECT_ID": 20, "GENDER": "M", "DOB": "1970-01-01"},
        {"SUBJECT_ID": 30, "GENDER": "F", "DOB": "1990-01-01"},
    ]
    events = [
        {"SUBJECT_ID": 10, "ITEMID": 211, "CHARTTIME": "2020-01-01 10:05:00", "VALUENUM": 72},
        {"SUBJECT_ID": 10, "ITEMID": 455, "CHARTTIME": "2020-01-01 10:10:00", "VALUENUM": 120},
        {"SUBJECT_ID": 10, "ITEMID": 8441, "CHARTTIME": "2020-01-01 10:15:00", "VALUENUM": 80},
        {"SUBJECT_ID": 20, "ITEMID": 220045, "CHARTTIME": "2020-01-01 10:05:00", "VALUENUM": 90},
        {"SUBJECT_ID": 20, "ITEMID": 220179, "CHARTTIME": "2020-01-01 10:10:00", "VALUENUM": 130},
        {"SUBJECT_ID": 20, "ITEMID": 220180, "CHARTTIME": "2020-01-01 10:15:00", "VALUENUM": 85},
        {"SUBJECT_ID": 10, "ITEMID": 51, "CHARTTIME": "2020-01-01 10:10:00", "VALUENUM": 250},
        {"SUBJECT_ID": 20, "ITEMID": 9999, "CHARTTIME": "2020-01-01 10:10:00", "VALUENUM": 1},
    ]
    return _write_mimic(
        directory,
        patients=patients,
        items=ITEMS,
        events=events,
    )


@pytest.mark.parametrize(
    "filename", ["PATIENTS.csv", "D_ITEMS.csv", "CHARTEVENTS.csv"]
)
def test_rejects_missing_mimic_files(tmp_path: Path, filename: str) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    (mimic_dir / filename).unlink()

    with pytest.raises(MimicAdapterError, match=filename):
        MimicIIIDemoAdapter(mimic_dir).convert(tmp_path / "out.csv")


@pytest.mark.parametrize(
    ("filename", "columns"),
    [
        ("PATIENTS.csv", ["SUBJECT_ID", "DOB"]),
        ("D_ITEMS.csv", ["ITEMID", "UNITNAME"]),
        ("CHARTEVENTS.csv", ["SUBJECT_ID", "ITEMID", "VALUENUM"]),
    ],
)
def test_rejects_missing_required_columns(
    tmp_path: Path, filename: str, columns: list[str]
) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    (mimic_dir / filename).write_text(",".join(columns) + "\n", encoding="utf-8")

    with pytest.raises(MimicAdapterError, match=filename):
        MimicIIIDemoAdapter(mimic_dir).convert(tmp_path / "out.csv")


def test_itemid_mapping_is_allowlisted_and_excludes_invasive_pressure(
    tmp_path: Path,
) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))

    mapping = adapter._discover_itemids()

    assert mapping == {
        211: "heart_rate",
        220045: "heart_rate",
        455: "systolic_bp",
        220179: "systolic_bp",
        8441: "diastolic_bp",
        220180: "diastolic_bp",
    }
    assert 51 not in mapping
    assert 442 not in mapping
    assert 220050 not in mapping
    assert 9999 not in mapping


def test_rejects_known_itemid_with_unexpected_label(tmp_path: Path) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    bad_items = [(item_id, "Unrelated measurement" if item_id == 455 else label)
                 for item_id, label in ITEMS]
    pd.DataFrame(bad_items, columns=["ITEMID", "LABEL"]).to_csv(
        mimic_dir / "D_ITEMS.csv", index=False
    )

    with pytest.raises(MimicAdapterError, match="ITEMID 455.*etiqueta inesperada"):
        MimicIIIDemoAdapter(mimic_dir).convert(tmp_path / "out.csv")


def test_converts_valid_measurements_and_reports_selection(tmp_path: Path) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))
    output = adapter.convert(tmp_path / "converted.csv")
    result = ClinicalCSVLoader.load(output)

    assert len(result) == 2
    assert set(result["subject_id"]) == {10, 20}
    assert result.loc[result["subject_id"] == 10, "heart_rate"].iloc[0] == 72
    assert adapter.last_report["unrecognized_item_rows"] == 2
    assert adapter.last_report["output_records"] == 2
    assert adapter.last_report["patients_without_complete_records"] == 1
    assert len(adapter.record_trace) == 2
    assert adapter.record_trace[0]["time_bin"] == "2020-01-01T10:00:00"


def test_measurements_are_joined_by_subject_and_hour(tmp_path: Path) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    events = pd.read_csv(mimic_dir / "CHARTEVENTS.csv")
    events.loc[events["SUBJECT_ID"] == 20, "SUBJECT_ID"] = 10
    events.to_csv(mimic_dir / "CHARTEVENTS.csv", index=False)

    adapter = MimicIIIDemoAdapter(mimic_dir)
    output = adapter.convert(tmp_path / "converted.csv")
    result = ClinicalCSVLoader.load(output)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["subject_id"] == 10
    assert row["heart_rate"] == pytest.approx(81)
    assert row["systolic_bp"] == pytest.approx(125)
    assert row["diastolic_bp"] == pytest.approx(82.5)


def test_reports_incomplete_measurement_bins_and_missing_values(
    tmp_path: Path,
) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    events = pd.read_csv(mimic_dir / "CHARTEVENTS.csv")
    events = events[events["SUBJECT_ID"] == 10]
    events = pd.concat(
        [
            events,
            pd.DataFrame(
                [
                    {
                        "SUBJECT_ID": 10,
                        "ITEMID": 211,
                        "CHARTTIME": "2020-01-01 11:10:00",
                        "VALUENUM": None,
                    },
                    {
                        "SUBJECT_ID": 10,
                        "ITEMID": 211,
                        "CHARTTIME": "2020-01-01 11:10:00",
                        "VALUENUM": "bad",
                    },
                    {
                        "SUBJECT_ID": 10,
                        "ITEMID": 211,
                        "CHARTTIME": "2020-01-01 11:15:00",
                        "VALUENUM": 75,
                    },
                    {
                        "SUBJECT_ID": 10,
                        "ITEMID": 455,
                        "CHARTTIME": "2020-01-01 11:20:00",
                        "VALUENUM": 122,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    events.to_csv(mimic_dir / "CHARTEVENTS.csv", index=False)
    adapter = MimicIIIDemoAdapter(mimic_dir)

    adapter.convert(tmp_path / "converted.csv")

    assert adapter.last_report["missing_valuenum_rows"] == 1
    assert adapter.last_report["invalid_valuenum_rows"] == 1
    assert adapter.last_report["incomplete_hour_bins"] == 1


def test_reports_exact_duplicates_and_aggregates_remaining_measurements(
    tmp_path: Path,
) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    events = pd.read_csv(mimic_dir / "CHARTEVENTS.csv")
    duplicate = events.iloc[[0]]
    pd.concat([events, duplicate], ignore_index=True).to_csv(
        mimic_dir / "CHARTEVENTS.csv", index=False
    )
    adapter = MimicIIIDemoAdapter(mimic_dir)

    output = adapter.convert(tmp_path / "converted.csv")
    result = ClinicalCSVLoader.load(output)

    assert adapter.last_report["exact_duplicate_measurements"] == 1
    assert result.loc[result["subject_id"] == 10, "heart_rate"].iloc[0] == 72
    assert adapter.record_trace[0]["source_event_count"] == 3


def test_invalid_times_and_values_are_counted_and_excluded(tmp_path: Path) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    events = pd.read_csv(mimic_dir / "CHARTEVENTS.csv")
    events = events[events["SUBJECT_ID"] == 10]
    extra = pd.DataFrame(
        [
            {"SUBJECT_ID": 10, "ITEMID": 211, "CHARTTIME": "not-a-date", "VALUENUM": 72},
            {"SUBJECT_ID": 10, "ITEMID": 211, "CHARTTIME": "2020-01-01 12:00", "VALUENUM": 999},
        ]
    )
    pd.concat([events, extra], ignore_index=True).to_csv(
        mimic_dir / "CHARTEVENTS.csv", index=False
    )
    adapter = MimicIIIDemoAdapter(mimic_dir)

    adapter.convert(tmp_path / "converted.csv")

    assert adapter.last_report["invalid_charttime_rows"] == 1
    assert adapter.last_report["out_of_range_measurement_rows"] == 1


@pytest.mark.parametrize(
    ("dob", "gender", "report_field"),
    [
        ("invalid", "F", "missing_dob_bins"),
        ("1980-01-01", "", "missing_gender_bins"),
    ],
)
def test_missing_age_or_gender_is_not_imputed(
    tmp_path: Path, dob: str, gender: str, report_field: str
) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    patients = pd.read_csv(mimic_dir / "PATIENTS.csv")
    patients.loc[patients["SUBJECT_ID"] == 10, "DOB"] = dob
    patients.loc[patients["SUBJECT_ID"] == 10, "GENDER"] = gender
    patients.to_csv(mimic_dir / "PATIENTS.csv", index=False)
    adapter = MimicIIIDemoAdapter(mimic_dir)

    output = adapter.convert(tmp_path / "converted.csv")
    result = ClinicalCSVLoader.load(output)

    assert 10 not in set(result["subject_id"])
    assert adapter.last_report[report_field] == 1
    assert adapter.last_report["patients_without_complete_records"] == 2


def test_reports_unmatched_subject_and_empty_complete_output(
    tmp_path: Path,
) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    events = pd.read_csv(mimic_dir / "CHARTEVENTS.csv")
    events.loc[events["SUBJECT_ID"] == 10, "SUBJECT_ID"] = 999
    events = events[events["ITEMID"].isin([211, 455, 8441])]
    events.to_csv(mimic_dir / "CHARTEVENTS.csv", index=False)
    adapter = MimicIIIDemoAdapter(mimic_dir)

    with pytest.raises(MimicAdapterError, match="No quedaron registros completos"):
        adapter.convert(tmp_path / "converted.csv")

    assert adapter.last_report["subjects_without_metadata"] == 1


def test_duplicate_patient_metadata_is_rejected(tmp_path: Path) -> None:
    mimic_dir = _valid_fixture(tmp_path / "mimic")
    patients = pd.read_csv(mimic_dir / "PATIENTS.csv")
    pd.concat([patients, patients.iloc[[0]]], ignore_index=True).to_csv(
        mimic_dir / "PATIENTS.csv", index=False
    )

    with pytest.raises(MimicAdapterError, match="SUBJECT_ID duplicado"):
        MimicIIIDemoAdapter(mimic_dir).convert(tmp_path / "converted.csv")


def test_output_integrates_with_pipeline_without_identity_in_analytical_data(
    tmp_path: Path,
) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))
    mimic_csv = adapter.convert(tmp_path / "converted.csv")
    records = ClinicalCSVLoader.load(mimic_csv)
    identity_repo = IdentityRepository()
    analytical_repo = AnalyticalRepository()
    pipeline = AnonymizationPipeline(
        IdentityCrypto(generate_master_key(tmp_path / "master.key")),
        identity_repo,
        analytical_repo,
    )

    identity_df, analytical_df = pipeline.process(records)

    assert {"nombre_cifrado", "rut_cifrado", "schnorr_public_key"}.issubset(
        identity_df.columns
    )
    assert {"nombre", "rut", "nombre_cifrado", "rut_cifrado"}.isdisjoint(
        analytical_df.columns
    )
    assert {"pseudonym", "schnorr_public_key", "record_id"}.issubset(
        analytical_df.columns
    )
    assert analytical_df["pseudonym"].nunique() == len(identity_df)
    assert analytical_df["schnorr_public_key"].nunique() == len(identity_df)
    assert analytical_df["pseudonym"].tolist() == identity_df["pseudonym"].tolist()
    assert not identity_df["nombre_cifrado"].str.contains(
        "Paciente Simulado MIMIC", regex=False
    ).any()

    identity_path = tmp_path / "D_id_protegido.csv"
    analytical_path = tmp_path / "D_ana_analitico.csv"
    identity_repo.save_csv(identity_path)
    analytical_repo.save_csv(analytical_path)
    saved_identity = pd.read_csv(identity_path)
    saved_analytical = pd.read_csv(analytical_path)
    assert saved_identity.columns.tolist() == identity_df.columns.tolist()
    assert saved_analytical.columns.tolist() == analytical_df.columns.tolist()
    assert {"nombre", "rut", "nombre_cifrado", "rut_cifrado"}.isdisjoint(
        saved_analytical.columns
    )
    assert saved_analytical["pseudonym"].tolist() == analytical_df["pseudonym"].tolist()


def test_mimic_synthetic_rut_passes_prompt_two_validation(tmp_path: Path) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))

    converted = adapter.convert(tmp_path / "converted.csv")
    validated = ClinicalCSVLoader.load(converted)

    assert len(validated) == 2
    assert validated["rut"].str.match(r"^\d+-[\dK]$").all()


@pytest.mark.parametrize("max_rows", [0, -1, True])
def test_rejects_invalid_max_rows(tmp_path: Path, max_rows: int) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))

    with pytest.raises(MimicAdapterError, match="max_rows"):
        adapter.convert(tmp_path / "converted.csv", max_rows=max_rows)


def test_max_rows_truncation_is_reported(tmp_path: Path) -> None:
    adapter = MimicIIIDemoAdapter(_valid_fixture(tmp_path / "mimic"))

    output = adapter.convert(tmp_path / "converted.csv", max_rows=1)
    result = ClinicalCSVLoader.load(output)

    assert len(result) == 1
    assert adapter.last_report["records_truncated_by_max_rows"] == 1
    assert adapter.last_report["output_records"] == 1
    assert len(adapter.record_trace) == 1
