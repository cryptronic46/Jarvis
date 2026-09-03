from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np


def wavs(path: Path):
    return sorted(str(p) for p in path.glob("*.wav") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positive-dir", required=True)
    ap.add_argument("--negative-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", default="hey_jarvis_v0.1")
    args = ap.parse_args()

    positive = wavs(Path(args.positive_dir))
    negative = wavs(Path(args.negative_dir))
    if len(positive) < 3:
        raise SystemExit("Need at least 3 positive Jarvis WAV clips")
    if len(negative) < 1:
        raise SystemExit("Need at least 1 negative-speech WAV clip (10s+ recommended)")

    import openwakeword
    from openwakeword import utils

    utils.download_models(model_names=[args.model])
    # Prefer the exact downloaded ONNX model path when available.
    model_path = None
    for key, meta in getattr(openwakeword, "MODELS", {}).items():
        if "jarvis" not in str(key).lower():
            continue
        candidate = meta.get("model_path") if isinstance(meta, dict) else None
        if candidate and str(candidate).lower().endswith(".onnx"):
            model_path = str(candidate)
            break
    model_ref = model_path or args.model

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_pkl = output.with_suffix(".training.pkl")
    openwakeword.train_custom_verifier(
        positive_reference_clips=positive,
        negative_reference_clips=negative,
        output_path=str(temp_pkl),
        model_name=model_ref,
        inference_framework="onnx",
    )
    with temp_pkl.open("rb") as f:
        pipeline = pickle.load(f)

    scaler = None
    classifier = None
    for _name, step in getattr(pipeline, "steps", []):
        if hasattr(step, "mean_") and hasattr(step, "scale_"):
            scaler = step
        if hasattr(step, "coef_") and hasattr(step, "intercept_"):
            classifier = step
    if scaler is None or classifier is None:
        raise RuntimeError("Could not extract StandardScaler/LogisticRegression parameters")

    model_key = Path(model_ref).stem if Path(str(model_ref)).suffix else str(args.model)
    np.savez_compressed(
        output,
        mean=np.asarray(scaler.mean_, dtype=np.float64),
        scale=np.asarray(scaler.scale_, dtype=np.float64),
        coef=np.asarray(classifier.coef_, dtype=np.float64),
        intercept=np.asarray(classifier.intercept_, dtype=np.float64),
        model_key=np.asarray([model_key]),
    )
    try:
        temp_pkl.unlink()
    except OSError:
        pass
    print(f"JARVIS wake verifier exported: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
