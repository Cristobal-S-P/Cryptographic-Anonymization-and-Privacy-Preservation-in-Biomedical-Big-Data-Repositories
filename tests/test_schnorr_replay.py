from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

import src.verifier as verifier_module
from src.crypto_utils import IdentityCrypto, SimplifiedSchnorr
from src.generate_key import generate_master_key
from src.ingestion import ClinicalCSVLoader
from src.models import SchnorrProof
from src.pipeline import AnonymizationPipeline
from src.repositories import AnalyticalRepository, IdentityRepository
from src.sample_data import generate
from src.verifier import AuthorizationError, RiskVerifier


def _prepared_pipeline(tmp_path: Path, patients: int = 2):
    input_path = generate(
        tmp_path / "clinical.csv", patients=patients, records_per_patient=1
    )
    records = ClinicalCSVLoader.load(input_path)
    crypto = IdentityCrypto(generate_master_key(tmp_path / "master.key"))
    identity_repo = IdentityRepository()
    analytical_repo = AnalyticalRepository()
    pipeline = AnonymizationPipeline(crypto, identity_repo, analytical_repo)
    pipeline.process(records)
    return pipeline, analytical_repo


def test_invalid_proof_does_not_consume_nonce_and_valid_proof_is_one_use(
    tmp_path: Path,
) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path, patients=1)
    credential = pipeline.credential_for_subject(1)
    verifier = RiskVerifier(analytical_repo)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)
    altered = SchnorrProof(
        commitment=proof.commitment,
        response=(proof.response + 1) % SimplifiedSchnorr.Q,
        nonce=proof.nonce,
    )

    assert not verifier.verify_proof(credential.pseudonym, altered, nonce)
    assert verifier.verify_proof(credential.pseudonym, proof, nonce)
    assert not verifier.verify_proof(credential.pseudonym, proof, nonce)


def test_tampered_commitment_and_challenge_context_are_rejected(
    tmp_path: Path,
) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path, patients=1)
    credential = pipeline.credential_for_subject(1)
    verifier = RiskVerifier(analytical_repo)

    commitment_nonce = verifier.new_nonce()
    valid_proof = verifier.build_proof(credential, commitment_nonce)
    altered_commitment = SchnorrProof(
        commitment=(valid_proof.commitment * SimplifiedSchnorr.G)
        % SimplifiedSchnorr.P,
        response=valid_proof.response,
        nonce=valid_proof.nonce,
    )
    assert not verifier.verify_proof(
        credential.pseudonym, altered_commitment, commitment_nonce
    )
    assert verifier.verify_proof(credential.pseudonym, valid_proof, commitment_nonce)

    challenge_nonce = verifier.new_nonce()
    challenge_altered_proof = verifier.build_proof(
        credential, challenge_nonce, consultation="different_scope"
    )
    assert not verifier.verify_proof(
        credential.pseudonym, challenge_altered_proof, challenge_nonce
    )
    correct_scope_proof = verifier.build_proof(credential, challenge_nonce)
    assert verifier.verify_proof(
        credential.pseudonym, correct_scope_proof, challenge_nonce
    )


def test_wrong_public_key_does_not_consume_nonce(tmp_path: Path) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path)
    credential = pipeline.credential_for_subject(1)
    other_credential = pipeline.credential_for_subject(2)
    verifier = RiskVerifier(analytical_repo)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)
    other_public_key = analytical_repo.get_public_key(other_credential.pseudonym)
    original_get_public_key = analytical_repo.get_public_key

    with patch.object(
        analytical_repo, "get_public_key", return_value=other_public_key
    ):
        assert not verifier.verify_proof(credential.pseudonym, proof, nonce)

    with patch.object(
        analytical_repo, "get_public_key", wraps=original_get_public_key
    ):
        assert verifier.verify_proof(credential.pseudonym, proof, nonce)


def test_wrong_pseudonym_does_not_consume_nonce(tmp_path: Path) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path)
    credential = pipeline.credential_for_subject(1)
    other_credential = pipeline.credential_for_subject(2)
    verifier = RiskVerifier(analytical_repo)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)

    assert not verifier.verify_proof(other_credential.pseudonym, proof, nonce)
    assert verifier.verify_proof(credential.pseudonym, proof, nonce)


def test_expired_nonce_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path, patients=1)
    credential = pipeline.credential_for_subject(1)
    clock = [100.0]
    monkeypatch.setattr(verifier_module, "monotonic", lambda: clock[0])
    verifier = RiskVerifier(analytical_repo, nonce_ttl_seconds=30)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)

    clock[0] = 130.0
    with pytest.raises(AuthorizationError):
        verifier.query_risk(credential.pseudonym, proof, nonce)
    assert not verifier.verify_proof(credential.pseudonym, proof, nonce)


@pytest.mark.parametrize("invalid_ttl", [0, -1, float("inf"), float("nan"), True])
def test_nonce_expiration_requires_a_finite_positive_value(
    tmp_path: Path, invalid_ttl: float
) -> None:
    _, analytical_repo = _prepared_pipeline(tmp_path, patients=1)

    with pytest.raises(ValueError, match="número positivo"):
        RiskVerifier(analytical_repo, nonce_ttl_seconds=invalid_ttl)


def test_concurrent_verification_accepts_nonce_exactly_once(tmp_path: Path) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path, patients=1)
    credential = pipeline.credential_for_subject(1)
    verifier = RiskVerifier(analytical_repo)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)
    workers = 8
    barrier = Barrier(workers)

    def verify_at_once() -> bool:
        barrier.wait()
        return verifier.verify_proof(credential.pseudonym, proof, nonce)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda _: verify_at_once(), range(workers)))

    assert results.count(True) == 1
    assert results.count(False) == workers - 1


def test_new_verifier_rejects_nonce_issued_before_restart(tmp_path: Path) -> None:
    pipeline, analytical_repo = _prepared_pipeline(tmp_path, patients=1)
    credential = pipeline.credential_for_subject(1)
    original_verifier = RiskVerifier(analytical_repo)
    nonce = original_verifier.new_nonce()
    proof = original_verifier.build_proof(credential, nonce)
    restarted_verifier = RiskVerifier(analytical_repo)

    assert not restarted_verifier.verify_proof(credential.pseudonym, proof, nonce)
    assert original_verifier.verify_proof(credential.pseudonym, proof, nonce)
