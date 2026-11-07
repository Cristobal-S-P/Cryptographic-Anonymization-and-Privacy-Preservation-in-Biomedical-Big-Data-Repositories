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

# Límites de validación técnica amplios; no son criterios diagnósticos.
AGE_MIN = 0
AGE_MAX = 120
SYSTOLIC_BP_MIN = 50
SYSTOLIC_BP_MAX = 260
DIASTOLIC_BP_MIN = 20
DIASTOLIC_BP_MAX = 180
HEART_RATE_MIN = 20
HEART_RATE_MAX = 250
