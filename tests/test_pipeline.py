from pathlib import Path

from src.config import MASTER_KEY_PATH
from src.crypto_utils import IdentityCrypto, SimplifiedSchnorr
from src.ingestion import ClinicalCSVLoader
from src.pipeline import AnonymizationPipeline
from src.repositories import AnalyticalRepository, IdentityRepository
from src.sample_data import generate
from src.models import SchnorrProof
from src.verifier import RiskVerifier


def test_one_identity_per_patient(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=4, records_per_patient=3)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = IdentityCrypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    identity_df, analytical_df = pipe.process(df)

    assert len(identity_df) == 4
    assert len(analytical_df) == 12
    assert analytical_df.groupby("pseudonym").size().eq(3).all()


def test_no_pii_in_analytical_repository(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=2, records_per_patient=2)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = IdentityCrypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    _, analytical_df = pipe.process(df)

    forbidden = {"nombre", "rut", "salt_b64", "schnorr_secret_cifrado"}
    assert forbidden.isdisjoint(set(analytical_df.columns))


def test_schnorr_query(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=2, records_per_patient=2)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = IdentityCrypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    pipe.process(df)

    credential = pipe.credential_for_subject(1)
    verifier = RiskVerifier(ana_repo)
    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)
    public_key = ana_repo.get_public_key(credential.pseudonym)

    assert public_key is not None
    assert SimplifiedSchnorr.verify(credential.pseudonym, public_key, proof) is True
    assert isinstance(verifier.verify_and_query(credential.pseudonym, proof), bool)

    # Alterar la respuesta invalida la demostración.
    tampered_response = SchnorrProof(
        commitment=proof.commitment,
        response=(proof.response + 1) % SimplifiedSchnorr.Q,
        nonce=proof.nonce,
    )
    assert SimplifiedSchnorr.verify(
        credential.pseudonym, public_key, tampered_response
    ) is False
    assert verifier.verify_and_query(credential.pseudonym, tampered_response) is False

    # Reutilizar la misma prueba con otro nonce también debe fallar.
    tampered_nonce = SchnorrProof(
        commitment=proof.commitment,
        response=proof.response,
        nonce=proof.nonce + "00",
    )
    assert SimplifiedSchnorr.verify(
        credential.pseudonym, public_key, tampered_nonce
    ) is False

    # Una prueba válida no puede trasladarse a otro pseudónimo.
    other_credential = pipe.credential_for_subject(2)
    other_public_key = ana_repo.get_public_key(other_credential.pseudonym)
    assert other_public_key is not None
    assert SimplifiedSchnorr.verify(
        other_credential.pseudonym, other_public_key, proof
    ) is False
