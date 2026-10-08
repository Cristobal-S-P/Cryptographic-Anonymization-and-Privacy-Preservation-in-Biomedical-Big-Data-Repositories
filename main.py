from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.config import DATA_INPUT, DATA_OUTPUT, MASTER_KEY_PATH
from src.crypto_utils import IdentityCrypto
from src.entropy import EntropyAnalyzer
from src.ingestion import ClinicalCSVLoader, IngestionError
from src.pipeline import AnonymizationPipeline
from src.mimic_adapter import MimicIIIDemoAdapter, MimicAdapterError
from src.repositories import AnalyticalRepository, IdentityRepository
from src.sample_data import generate
from src.verifier import RiskVerifier


def run(input_csv: Path, demo_subject: int | None = None) -> None:
    crypto = IdentityCrypto(MASTER_KEY_PATH)
    identity_repo = IdentityRepository()
    analytical_repo = AnalyticalRepository()
    pipeline = AnonymizationPipeline(crypto, identity_repo, analytical_repo)

    df = ClinicalCSVLoader.load(input_csv)
    identity_df, analytical_df = pipeline.process(df)

    identity_path = DATA_OUTPUT / "D_id_protegido.csv"
    analytical_path = DATA_OUTPUT / "D_ana_analitico.csv"
    entropy_path = DATA_OUTPUT / "entropia.csv"

    identity_repo.save_csv(identity_path)
    analytical_repo.save_csv(analytical_path)

    entropy_report = EntropyAnalyzer.report(analytical_df)
    pd.DataFrame([entropy_report]).to_csv(entropy_path, index=False)

    print("\n=== PIPELINE COMPLETADO ===")
    print(f"Registros clínicos procesados : {len(df)}")
    print(f"Pacientes únicos             : {identity_df['subject_id'].nunique()}")
    print(f"D_id protegido               : {identity_path}")
    print(f"D_ana analítico              : {analytical_path}")
    print(f"Reporte de entropía          : {entropy_path}")

    forbidden_pii = {"nombre", "rut", "salt_b64", "schnorr_secret_cifrado"}
    pii_detected = sorted(forbidden_pii.intersection(analytical_df.columns))
    print(f"PII directa detectada en D_ana: {'SÍ -> ' + ', '.join(pii_detected) if pii_detected else 'NO'}")

    print("\nEntropía:")
    for key, value in entropy_report.items():
        print(f"  {key}: {value:.4f}")

    if demo_subject is not None:
        credential = pipeline.credential_for_subject(demo_subject)
        verifier = RiskVerifier(analytical_repo)
        nonce = verifier.new_nonce()
        proof = verifier.build_proof(credential, nonce)
        belongs = verifier.verify_and_query(credential.pseudonym, proof)
        print("\n=== DEMOSTRACIÓN ZK SIMPLIFICADA ===")
        print(f"Paciente consultado (subject_id local): {demo_subject}")
        print(
            "PII enviada al repositorio analítico : "
            + ("NO" if not pii_detected else "SÍ")
        )
        print(f"Pseudónimo                             : {credential.pseudonym[:16]}...")
        print(f"¿Pertenece a cohorte de riesgo?        : {'SÍ' if belongs else 'NO'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Proyecto 7 - anonimización biomédica")
    parser.add_argument(
        "--input",
        type=Path,
        default=DATA_INPUT / "clinical_demo.csv",
        help="CSV de entrada con PII simulada y variables clínicas.",
    )
    parser.add_argument(
        "--mimic-dir",
        type=Path,
        default=None,
        help="Carpeta que contiene PATIENTS.csv, D_ITEMS.csv y CHARTEVENTS.csv de MIMIC-III Demo.",
    )
    parser.add_argument(
        "--generate-demo",
        action="store_true",
        help="Genera un CSV sintético reproducible antes de ejecutar.",
    )
    parser.add_argument(
        "--demo-subject",
        type=int,
        default=1,
        help="subject_id usado para demostrar la prueba Schnorr simplificada.",
    )
    parser.add_argument(
        "--patients",
        type=int,
        default=20,
        help="Número de pacientes sintéticos cuando se usa --generate-demo (default: 20).",
    )
    parser.add_argument(
        "--records-per-patient",
        type=int,
        default=5,
        help="Registros sintéticos por paciente cuando se usa --generate-demo (default: 5).",
    )
    args = parser.parse_args()

    try:
        if args.mimic_dir is not None:
            MimicIIIDemoAdapter(args.mimic_dir).convert(args.input)
            print(f"MIMIC-III Demo adaptado a: {args.input}")
        elif args.generate_demo or not args.input.exists():
            if args.patients <= 0 or args.records_per_patient <= 0:
                raise ValueError("--patients y --records-per-patient deben ser mayores que cero.")
            generate(
                args.input,
                patients=args.patients,
                records_per_patient=args.records_per_patient,
            )
            print(
                f"Dataset sintético generado en: {args.input} "
                f"({args.patients} pacientes × {args.records_per_patient} registros)"
            )

        run(args.input, args.demo_subject)
    except (IngestionError, MimicAdapterError, ValueError, KeyError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
