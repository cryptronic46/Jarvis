from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(slots=True)
class NumpyWakeVerifier:
    """NumPy-only runtime form of openWakeWord's custom verifier.

    The official trainer uses a StandardScaler + LogisticRegression pipeline.
    JARVIS exports only the learned numeric parameters so Windows inference does
    not need to import SciPy/scikit-learn native extensions.
    """

    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: np.ndarray
    model_key: str = "jarvis"

    @classmethod
    def load(cls, path: str | Path) -> "NumpyWakeVerifier":
        source = Path(path)
        with np.load(source, allow_pickle=False) as data:
            mean = np.asarray(data["mean"], dtype=np.float64).reshape(-1)
            scale = np.asarray(data["scale"], dtype=np.float64).reshape(-1)
            coef = np.asarray(data["coef"], dtype=np.float64)
            intercept = np.asarray(data["intercept"], dtype=np.float64).reshape(-1)
            model_key_arr = data.get("model_key")
            if model_key_arr is None:
                model_key = "jarvis"
            else:
                model_key = str(np.asarray(model_key_arr).reshape(-1)[0])
        if mean.size == 0 or scale.size != mean.size:
            raise ValueError("WAKE_VERIFIER_SCALER_INVALID")
        if coef.ndim == 1:
            coef = coef.reshape(1, -1)
        if coef.shape[1] != mean.size:
            raise ValueError("WAKE_VERIFIER_COEF_INVALID")
        if intercept.size != coef.shape[0]:
            raise ValueError("WAKE_VERIFIER_INTERCEPT_INVALID")
        scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
        return cls(mean=mean, scale=scale, coef=coef, intercept=intercept, model_key=model_key)

    def score(self, features: Any) -> float:
        x = np.asarray(features, dtype=np.float64).reshape(-1)
        if x.size != self.mean.size:
            raise ValueError(f"WAKE_VERIFIER_FEATURE_SIZE:{x.size}!={self.mean.size}")
        z = (x - self.mean) / self.scale
        logits = self.coef @ z + self.intercept
        # Official custom verifier is binary logistic regression. For the
        # binary sklearn shape (1, n_features), sigmoid(logit) is class-1 prob.
        if logits.size == 1:
            value = float(np.clip(logits[0], -60.0, 60.0))
            return float(1.0 / (1.0 + np.exp(-value)))
        logits = logits - float(np.max(logits))
        probs = np.exp(logits)
        probs /= float(np.sum(probs) or 1.0)
        return float(probs[-1])

    def status(self) -> dict[str, Any]:
        return {
            "loaded": True,
            "backend": "numpy-logistic",
            "model_key": self.model_key,
            "features": int(self.mean.size),
        }
