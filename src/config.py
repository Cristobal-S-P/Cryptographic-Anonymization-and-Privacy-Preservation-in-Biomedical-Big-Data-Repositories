from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_INPUT = ROOT / "data" / "input"
DATA_OUTPUT = ROOT / "data" / "output"
KEY_DIR = ROOT / "keys"
MASTER_KEY_PATH = KEY_DIR / "master.key"

# Criterio configurable para formar una cohorte de riesgo; no constituye diagnóstico clínico.
SYS_RISK_THRESHOLD = 140
DIA_RISK_THRESHOLD = 90
PBKDF2_ITERATIONS = 310_000
SALT_BYTES = 16

REQUIRED_COLUMNS = {
    "subject_id",
    "record_id",
    "nombre",
    "rut",
    "edad",
    "sexo",
    "systolic_bp",
    "diastolic_bp",
    "heart_rate",
}
