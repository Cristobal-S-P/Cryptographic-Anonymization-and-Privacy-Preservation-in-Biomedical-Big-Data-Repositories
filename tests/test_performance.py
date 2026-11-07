from __future__ import annotations

import platform
import statistics
import sys
import timeit
from pathlib import Path
from typing import Callable

import cryptography
import pandas as pd
import pytest

from src.crypto_utils import IdentityCrypto, SimplifiedSchnorr
from src.entropy import EntropyAnalyzer
from src.generate_key import generate_master_key
from src.ingestion import ClinicalCSVLoader
from src.models import PatientCredential, SchnorrProof
from src.pipeline import AnonymizationPipeline
from src.repositories import AnalyticalRepository, IdentityRepository
from src.sample_data import generate
from src.verifier import AuthorizationError, RiskVerifier


PATIENTS = 20
RECORDS_PER_PATIENT = 5
TIMEIT_ITERATIONS = 10
TIMEIT_REPEATS = 3


def _prepare_requests(
    verifier: RiskVerifier,
    pseudonym: str,
    credential: PatientCredential,
    count: int,
) -> list[tuple[str, SchnorrProof, str]]:
    requests = []
    for _ in range(count):
        nonce = verifier.new_nonce()
        proof = verifier.build_proof(credential, nonce)
        requests.append((pseudonym, proof, nonce))
    return requests


def _measure(
    operation: Callable[[str, SchnorrProof, str], object],
    requests: list[tuple[str, SchnorrProof, str]],
) -> tuple[float, list[object]]:
    request_iterator = iter(requests)
    results: list[object] = []

    def invoke() -> None:
        results.append(operation(*next(request_iterator)))

    elapsed = timeit.repeat(
        invoke, number=TIMEIT_ITERATIONS, repeat=TIMEIT_REPEATS
    )
    return statistics.median(elapsed) / TIMEIT_ITERATIONS, results


def test_reproducible_performance_and_perturbation_report(
    tmp_path: Path,
) -> None:
    input_csv = generate(
        tmp_path / "clinical_demo.csv",
        patients=PATIENTS,
        records_per_patient=RECORDS_PER_PATIENT,
    )
    records = ClinicalCSVLoader.load(input_csv)
    analytical_repo = AnalyticalRepository()
    identity_repo = IdentityRepository()
    pipeline = AnonymizationPipeline(
        IdentityCrypto(generate_master_key(tmp_path / "master.key")),
        identity_repo,
        analytical_repo,
    )
    identity_df, analytical_df = pipeline.process(records)

    output_dir = tmp_path / "output"
    identity_csv = output_dir / "D_id_protegido.csv"
    analytical_csv = output_dir / "D_ana_analitico.csv"
    entropy_csv = output_dir / "entropia.csv"
    identity_repo.save_csv(identity_csv)
    analytical_repo.save_csv(analytical_csv)
    pd.DataFrame([EntropyAnalyzer.report(analytical_df)]).to_csv(
        entropy_csv, index=False
    )

    credential = pipeline.credential_for_subject(1)
    verifier = RiskVerifier(analytical_repo)
    verify_requests = _prepare_requests(
        verifier,
        credential.pseudonym,
        credential,
        TIMEIT_ITERATIONS * TIMEIT_REPEATS,
    )
    verify_ms, verification_results = _measure(
        verifier.verify_proof, verify_requests
    )
    assert all(result is True for result in verification_results)

    query_verifier = RiskVerifier(analytical_repo)
    query_requests = _prepare_requests(
        query_verifier,
        credential.pseudonym,
        credential,
        TIMEIT_ITERATIONS * TIMEIT_REPEATS,
    )
    query_ms, query_results = _measure(
        query_verifier.query_risk, query_requests
    )
    assert all(isinstance(result, bool) for result in query_results)

    other_credential = pipeline.credential_for_subject(2)
    perturbation_verifier = RiskVerifier(analytical_repo)
    valid_nonce = perturbation_verifier.new_nonce()
    valid_proof = perturbation_verifier.build_proof(credential, valid_nonce)
    invalid_commitment = SchnorrProof(
        commitment=2, response=valid_proof.response, nonce=valid_proof.nonce
    )
    invalid_response = SchnorrProof(
        commitment=valid_proof.commitment,
        response=(valid_proof.response + 1) % SimplifiedSchnorr.Q,
        nonce=valid_proof.nonce,
    )
    altered_nonce = "0" * (SimplifiedSchnorr.NONCE_BYTES * 2)
    if altered_nonce == valid_proof.nonce:
        altered_nonce = "1" * (SimplifiedSchnorr.NONCE_BYTES * 2)
    altered_proof_nonce = SchnorrProof(
        commitment=valid_proof.commitment,
        response=valid_proof.response,
        nonce=altered_nonce,
    )
    wrong_pseudonym_nonce = perturbation_verifier.new_nonce()
    wrong_pseudonym_proof = perturbation_verifier.build_proof(
        credential, wrong_pseudonym_nonce
    )
    wrong_scope_nonce = perturbation_verifier.new_nonce()
    wrong_scope_proof = perturbation_verifier.build_proof(
        credential, wrong_scope_nonce, consultation="different_query"
    )
    perturbations = [
        ("invalid commitment", credential.pseudonym, invalid_commitment, valid_nonce),
        ("altered response", credential.pseudonym, invalid_response, valid_nonce),
        ("altered proof nonce", credential.pseudonym, altered_proof_nonce, valid_nonce),
        (
            "wrong pseudonym",
            other_credential.pseudonym,
            wrong_pseudonym_proof,
            wrong_pseudonym_nonce,
        ),
        (
            "wrong consultation",
            credential.pseudonym,
            wrong_scope_proof,
            wrong_scope_nonce,
        ),
    ]
    rejected = 0
    for _, pseudonym, proof, nonce in perturbations:
        try:
            perturbation_verifier.query_risk(pseudonym, proof, nonce)
        except AuthorizationError:
            rejected += 1
    assert rejected == len(perturbations)

    csv_sizes = {
        "input": input_csv.stat().st_size,
        "D_id_protegido": identity_csv.stat().st_size,
        "D_ana_analitico": analytical_csv.stat().st_size,
        "entropia": entropy_csv.stat().st_size,
    }
    assert len(records) == PATIENTS * RECORDS_PER_PATIENT
    assert len(identity_df) == PATIENTS
    assert all(size > 0 for size in csv_sizes.values())

    report_lines = [
        "\n=== INFORME REPRODUCIBLE: RENDIMIENTO Y PERTURBACIONES ===",
        f"Entorno: {platform.platform()} ({platform.machine()})",
        f"Procesador: {platform.processor() or 'no reportado'}",
        f"Python {sys.version.split()[0]} | pandas {pd.__version__} | "
        f"cryptography {cryptography.__version__} | pytest {pytest.__version__}",
        f"Dataset: {len(records)} registros procesados; {len(identity_df)} pacientes",
        "Tamano CSV (bytes): "
        + ", ".join(f"{name}={size}" for name, size in csv_sizes.items()),
        (
            f"timeit: mediana de {TIMEIT_REPEATS} repeticiones x "
            f"{TIMEIT_ITERATIONS} llamadas; "
            f"verify_proof={verify_ms:.3f} ms/call, "
            f"query_risk={query_ms:.3f} ms/call"
        ),
        f"Perturbaciones rechazadas: {rejected}/{len(perturbations)}",
    ]
    print("\n".join(report_lines))
