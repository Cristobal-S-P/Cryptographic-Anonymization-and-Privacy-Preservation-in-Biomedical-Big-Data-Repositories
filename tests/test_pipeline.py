from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import main as app
from src.crypto_utils import IdentityCrypto, SimplifiedSchnorr
from src.generate_key import generate_master_key
from src.ingestion import ClinicalCSVLoader
from src.pipeline import AnonymizationPipeline
from src.repositories import AnalyticalRepository, IdentityRepository
from src.sample_data import generate
from src.models import SchnorrProof
from src.verifier import AuthorizationError, RiskVerifier


def _identity_crypto(key_path: Path) -> IdentityCrypto:
    generate_master_key(key_path)
    return IdentityCrypto(key_path)


def test_one_identity_per_patient(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=4, records_per_patient=3)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
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
    crypto = _identity_crypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    identity_df, analytical_df = pipe.process(df)

    forbidden = {
        "nombre",
        "rut",
        "salt_b64",
        "schnorr_secret",
        "schnorr_secret_cifrado",
    }
    assert forbidden.isdisjoint(set(analytical_df.columns))
    assert "schnorr_secret" not in identity_df.columns
    assert "schnorr_secret_cifrado" not in identity_df.columns
    credential = pipe.credential_for_subject(1)
    assert "schnorr_secret" not in repr(credential)


def test_schnorr_group_parameters() -> None:
    schnorr = SimplifiedSchnorr
    expected_p = (
        "87A8E61DB4B6663CFFBBD19C651959998CEEF608660DD0F2"
        "5D2CEED4435E3B00E00DF8F1D61957D4FAF7DF4561B2AA30"
        "16C3D91134096FAA3BF4296D830E9A7C209E0C6497517ABD"
        "5A8A9D306BCF67ED91F9E6725B4758C022E0B1EF4275BF7B"
        "6C5BFC11D45F9088B941F54EB1E59BB8BC39A0BF12307F5C"
        "4FDB70C581B23F76B63ACAE1CAA6B7902D52526735488A0E"
        "F13C6D9A51BFA4AB3AD8347796524D8EF6A167B5A41825D9"
        "67E144E5140564251CCACB83E6B486F6B3CA3F7971506026"
        "C0B857F689962856DED4010ABD0BE621C3A3960A54E710C3"
        "75F26375D7014103A4B54330C198AF126116D2276E11715F"
        "693877FAD7EF09CADB094AE91E1A1597"
    )
    expected_q = (
        "8CF83642A709A097B447997640129DA299B1A47D"
        "1EB3750BA308B0FE64F5FBD3"
    )
    expected_g = (
        "3FB32C9B73134D0B2E77506660EDBD484CA7B18F21EF2054"
        "07F4793A1A0BA12510DBC15077BE463FFF4FED4AAC0BB555"
        "BE3A6C1B0C6B47B1BC3773BF7E8C6F62901228F8C28CBB18"
        "A55AE31341000A650196F931C77A57F2DDF463E5E9EC144B"
        "777DE62AAAB8A8628AC376D282D6ED3864E67982428EBC83"
        "1D14348F6F2F9193B5045AF2767164E1DFC967C1FB3F2E55"
        "A4BD1BFFE83B9C80D052B985D182EA0ADB2A3B7313D3FE14"
        "C8484B1E052588B9B7D2BBD2DF016199ECD06E1557CD0915"
        "B3353BBB64E0EC377FD028370DF92B52C7891428CDC67EB6"
        "184B523D1DB246C32F63078490F00EF8D647D148D4795451"
        "5E2327CFEF98C582664B4C0F6CC41659"
    )

    # Exact hexadecimal values transcribed from RFC 5114 section 2.3.
    assert format(schnorr.P, "X") == expected_p
    assert format(schnorr.Q, "X") == expected_q
    assert format(schnorr.G, "X") == expected_g
    assert schnorr.P.bit_length() == 2048
    assert schnorr.Q.bit_length() == 256
    assert (schnorr.P - 1) % schnorr.Q == 0
    assert 1 < schnorr.G < schnorr.P
    assert pow(schnorr.G, schnorr.Q, schnorr.P) == 1
    assert schnorr.G != 1
    assert schnorr._valid_group_element(schnorr.G)


def test_schnorr_group_value_ranges() -> None:
    schnorr = SimplifiedSchnorr
    generated_secret = schnorr.generate_secret()
    assert schnorr._valid_scalar(generated_secret)
    assert schnorr._valid_group_element(schnorr.public_key(generated_secret))

    for invalid_scalar in (0, -1, schnorr.Q, schnorr.Q + 1, True):
        assert not schnorr._valid_scalar(invalid_scalar)
        try:
            schnorr.public_key(invalid_scalar)
        except ValueError:
            pass
        else:
            raise AssertionError("public_key accepted an out-of-range secret")

    for invalid_element in (0, 1, 2, schnorr.P - 1, schnorr.P, schnorr.P + 1):
        assert not schnorr._valid_group_element(invalid_element)

    assert schnorr._valid_response(0)
    assert schnorr._valid_response(schnorr.Q - 1)
    for invalid_response in (-1, schnorr.Q, schnorr.Q + 1, True):
        assert not schnorr._valid_response(invalid_response)


def test_schnorr_proof_validation_and_session_replay(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=2, records_per_patient=2)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
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
    assert SimplifiedSchnorr._valid_group_element(public_key)
    assert SimplifiedSchnorr._valid_group_element(proof.commitment)
    assert SimplifiedSchnorr._valid_response(proof.response)
    assert SimplifiedSchnorr.verify(
        credential.pseudonym, public_key, proof, expected_nonce=nonce
    )
    assert verifier.verify_proof(credential.pseudonym, proof, nonce)

    # Una prueba válida es de un solo uso y queda vinculada al reto de su sesión.
    assert not verifier.verify_proof(credential.pseudonym, proof, nonce)
    next_session_nonce = verifier.new_nonce()
    assert not verifier.verify_proof(
        credential.pseudonym, proof, next_session_nonce
    )

    # Alterar la respuesta invalida la prueba.
    altered_session_nonce = verifier.new_nonce()
    fresh_proof = verifier.build_proof(credential, altered_session_nonce)
    tampered_response = SchnorrProof(
        commitment=fresh_proof.commitment,
        response=(fresh_proof.response + 1) % SimplifiedSchnorr.Q,
        nonce=fresh_proof.nonce,
    )
    assert SimplifiedSchnorr.verify(
        credential.pseudonym, public_key, tampered_response,
        expected_nonce=altered_session_nonce,
    ) is False
    assert verifier.verify_proof(
        credential.pseudonym, tampered_response, altered_session_nonce
    ) is False

    # Un nonce esperado distinto del nonce firmado se rechaza.
    wrong_challenge_nonce = verifier.new_nonce()
    assert not verifier.verify_proof(
        credential.pseudonym, fresh_proof, wrong_challenge_nonce
    )

    # Los elementos del grupo y la respuesta fuera de rango se rechazan.
    for invalid_proof in (
        SchnorrProof(commitment=0, response=proof.response, nonce=nonce),
        SchnorrProof(commitment=2, response=proof.response, nonce=nonce),
        SchnorrProof(
            commitment=proof.commitment,
            response=SimplifiedSchnorr.Q,
            nonce=nonce,
        ),
    ):
        assert not SimplifiedSchnorr.verify(
            credential.pseudonym, public_key, invalid_proof, expected_nonce=nonce
        )
    assert not SimplifiedSchnorr.verify(
        credential.pseudonym,
        SimplifiedSchnorr.P,
        proof,
        expected_nonce=nonce,
    )

    # La prueba está vinculada tanto a la clave como al pseudónimo.
    other_credential = pipe.credential_for_subject(2)
    other_public_key = ana_repo.get_public_key(other_credential.pseudonym)
    assert other_public_key is not None
    assert SimplifiedSchnorr.verify(
        other_credential.pseudonym,
        other_public_key,
        proof,
        expected_nonce=nonce,
    ) is False


def test_query_risk_rejects_missing_proof(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=1, records_per_patient=1)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    pipe.process(df)
    credential = pipe.credential_for_subject(1)
    verifier = RiskVerifier(ana_repo)

    with patch.object(ana_repo, "get_risk", wraps=ana_repo.get_risk) as get_risk:
        with pytest.raises(AuthorizationError):
            verifier.query_risk(credential.pseudonym)
        get_risk.assert_not_called()


def test_query_risk_rejects_invalid_proof_and_replayed_nonce(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=1, records_per_patient=1)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    pipe.process(df)
    credential = pipe.credential_for_subject(1)
    verifier = RiskVerifier(ana_repo)

    nonce = verifier.new_nonce()
    proof = verifier.build_proof(credential, nonce)
    with patch.object(ana_repo, "get_risk", wraps=ana_repo.get_risk) as get_risk:
        assert isinstance(verifier.query_risk(credential.pseudonym, proof, nonce), bool)
        with pytest.raises(AuthorizationError):
            verifier.query_risk(credential.pseudonym, proof, nonce)
        assert get_risk.call_count == 1

        invalid_nonce = verifier.new_nonce()
        valid_proof = verifier.build_proof(credential, invalid_nonce)
        invalid_proof = SchnorrProof(
            commitment=valid_proof.commitment,
            response=(valid_proof.response + 1) % SimplifiedSchnorr.Q,
            nonce=valid_proof.nonce,
        )
        with pytest.raises(AuthorizationError):
            verifier.query_risk(credential.pseudonym, invalid_proof, invalid_nonce)
        assert get_risk.call_count == 1


def test_query_risk_rejects_proof_for_other_pseudonym_or_query(
    tmp_path: Path,
) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=2, records_per_patient=1)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    pipe.process(df)
    credential = pipe.credential_for_subject(1)
    other_credential = pipe.credential_for_subject(2)
    verifier = RiskVerifier(ana_repo)

    pseudonym_nonce = verifier.new_nonce()
    pseudonym_proof = verifier.build_proof(credential, pseudonym_nonce)
    query_nonce = verifier.new_nonce()
    query_proof = verifier.build_proof(
        credential, query_nonce, consultation="another_query"
    )
    with patch.object(ana_repo, "get_risk", wraps=ana_repo.get_risk) as get_risk:
        with pytest.raises(AuthorizationError):
            verifier.query_risk(
                other_credential.pseudonym, pseudonym_proof, pseudonym_nonce
            )
        with pytest.raises(AuthorizationError):
            verifier.query_risk(credential.pseudonym, query_proof, query_nonce)
        get_risk.assert_not_called()


def test_query_risk_nonce_is_scoped_to_verifier_instance(tmp_path: Path) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=1, records_per_patient=1)
    df = ClinicalCSVLoader.load(csv_path)
    crypto = _identity_crypto(tmp_path / "master.key")
    id_repo = IdentityRepository()
    ana_repo = AnalyticalRepository()
    pipe = AnonymizationPipeline(crypto, id_repo, ana_repo)
    pipe.process(df)
    credential = pipe.credential_for_subject(1)
    issuer = RiskVerifier(ana_repo)
    separate_instance = RiskVerifier(ana_repo)
    nonce = issuer.new_nonce()
    proof = issuer.build_proof(credential, nonce)

    with patch.object(ana_repo, "get_risk", wraps=ana_repo.get_risk) as get_risk:
        with pytest.raises(AuthorizationError):
            separate_instance.query_risk(credential.pseudonym, proof, nonce)
        get_risk.assert_not_called()


def test_demo_output_omits_local_subject_and_pseudonym(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = generate(tmp_path / "demo.csv", patients=1, records_per_patient=1)
    monkeypatch.setattr(app, "MASTER_KEY_PATH", tmp_path / "master.key")
    monkeypatch.setattr(app, "DATA_OUTPUT", tmp_path / "output")
    generate_master_key(tmp_path / "master.key")

    app.run(csv_path, demo_subject=1)
    output = capsys.readouterr().out
    analytical_df = pd.read_csv(tmp_path / "output" / "D_ana_analitico.csv")
    pseudonym = analytical_df.loc[0, "pseudonym"]

    assert "subject_id local" not in output
    assert "Pseudónimo" not in output
    assert pseudonym not in output
    assert "¿Consulta clínica autorizada?" not in output
    assert "¿Prueba de posesión de clave válida?   : SÍ" in output
    assert (
        "Una prueba válida demuestra posesión de una clave; "
        "no constituye autorización clínica ni verifica la veracidad del dato."
    ) in output
    assert (
        "Entropía (métrica complementaria; no demuestra anonimato):" in output
    )
    assert "anonimato" not in output.lower().replace("no demuestra anonimato", "")
