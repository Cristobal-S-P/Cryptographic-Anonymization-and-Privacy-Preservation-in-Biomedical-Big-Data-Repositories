from dataclasses import dataclass


@dataclass(frozen=True)
class ClinicalRecord:
    subject_id: int
    record_id: int
    nombre: str
    rut: str
    edad: int
    sexo: str
    systolic_bp: float
    diastolic_bp: float
    heart_rate: float


@dataclass(frozen=True)
class PatientCredential:
    pseudonym: str
    schnorr_secret: int


@dataclass(frozen=True)
class SchnorrProof:
    commitment: int
    response: int
    nonce: str
