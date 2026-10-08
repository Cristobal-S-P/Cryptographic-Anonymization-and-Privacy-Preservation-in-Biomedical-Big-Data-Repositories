from __future__ import annotations

import random
from pathlib import Path

import pandas as pd


def _rut_from_number(number: int) -> str:
    digits = list(map(int, str(number)))
    factors = [2, 3, 4, 5, 6, 7]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        total += digit * factors[i % len(factors)]
    dv = 11 - (total % 11)
    check = "0" if dv == 11 else "K" if dv == 10 else str(dv)
    return f"{number}-{check}"


def generate(path: Path, patients: int = 20, records_per_patient: int = 5) -> Path:
    random.seed(7)
    rows = []
    record_id = 1
    for subject_id in range(1, patients + 1):
        age = random.randint(20, 85)
        sex = random.choice(["F", "M"])
        rut = _rut_from_number(10_000_000 + subject_id * 137)
        name = f"Paciente Simulado {subject_id:03d}"
        base_sys = random.randint(105, 155)
        base_dia = random.randint(65, 98)
        for _ in range(records_per_patient):
            sys_bp = max(base_sys + random.randint(-8, 8), base_dia + 10)
            dia_bp = base_dia + random.randint(-5, 5)
            heart_rate = random.randint(55, 105)
            rows.append(
                {
                    "subject_id": subject_id,
                    "record_id": record_id,
                    "nombre": name,
                    "rut": rut,
                    "edad": age,
                    "sexo": sex,
                    "systolic_bp": sys_bp,
                    "diastolic_bp": dia_bp,
                    "heart_rate": heart_rate,
                }
            )
            record_id += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
