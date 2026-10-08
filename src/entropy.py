from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

import pandas as pd


class EntropyAnalyzer:
    @staticmethod
    def shannon(values: Iterable[str]) -> float:
        values = list(values)
        if not values:
            return 0.0
        counts = Counter(values)
        n = len(values)
        return -sum((c / n) * math.log2(c / n) for c in counts.values())

    @staticmethod
    def hexadecimal_character_entropy(tokens: Iterable[str]) -> float:
        chars = [ch for token in tokens for ch in str(token).lower() if ch in "0123456789abcdef"]
        return EntropyAnalyzer.shannon(chars)

    @staticmethod
    def report(analytical_df: pd.DataFrame) -> dict[str, float]:
        report: dict[str, float] = {}
        if "pseudonym" in analytical_df:
            report["entropia_hex_pseudonimo_bits_por_caracter"] = (
                EntropyAnalyzer.hexadecimal_character_entropy(analytical_df["pseudonym"].unique())
            )
        if "sexo" in analytical_df:
            report["entropia_sexo_bits"] = EntropyAnalyzer.shannon(analytical_df["sexo"].astype(str))
        if "age_group" in analytical_df:
            report["entropia_grupo_edad_bits"] = EntropyAnalyzer.shannon(analytical_df["age_group"].astype(str))
        if "risk_group" in analytical_df:
            report["entropia_cohorte_riesgo_bits"] = EntropyAnalyzer.shannon(analytical_df["risk_group"].astype(str))
        return report
