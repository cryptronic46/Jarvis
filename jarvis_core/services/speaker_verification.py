from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import wave

import numpy as np

from jarvis_core.core.events import EventBus


CAMPLUS_SHA256 = "8ebcd0b04c1bb50d5fe77166f9a123206bf08ed14bcfd6a0b95fe8fcb2e25926"


@dataclass(slots=True)
class SpeakerConfig:
    enabled: bool = True
    profile_name: str = "owner"
    profile_dir: str = "voice_profiles"
    model_path: str = "models/voiceid/3d_speaker-speech_campplus_sv_en_voxceleb_16k.pt"
    model_sha256: str = CAMPLUS_SHA256
    threshold: float = 0.45
    min_seconds: float = 0.7
    enrollment_samples: int = 5


class SpeakerVerifier:
    """
    Owner-only voice gate using a TorchScript CAM++ speaker embedding model.

    Pipeline:
      PCM WAV -> 16 kHz mono -> Kaldi 80-bin FBank -> mean normalization
      -> CAM++ embedding -> L2 normalization -> cosine similarity

    Persistent enrollment stores only an averaged normalized embedding.
    Raw enrollment recordings are deleted by the CLI after enrollment.

    This is a convenience filter, not high-security biometric authentication.
    """

    def __init__(self, events: EventBus, config: SpeakerConfig):
        self.events = events
        self.config = config
        self._model = None
        self._model_error: str | None = None

        self.profile_dir = Path(config.profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    @property
    def profile_path(self) -> Path:
        return self.profile_dir / f"{self.config.profile_name}.npz"

    @property
    def metadata_path(self) -> Path:
        return self.profile_dir / f"{self.config.profile_name}.json"

    @property
    def model_path(self) -> Path:
        return Path(self.config.model_path)

    def enrolled(self) -> bool:
        return self.profile_path.exists()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def status(self) -> dict[str, Any]:
        metadata = None
        if self.metadata_path.exists():
            try:
                metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except Exception:
                metadata = None

        model_exists = self.model_path.exists()
        return {
            "enabled": self.config.enabled,
            "profile_name": self.config.profile_name,
            "enrolled": self.enrolled(),
            "threshold": self.config.threshold,
            "enrollment_samples": self.config.enrollment_samples,
            "backend": "torchscript-campplus",
            "model_path": str(self.model_path),
            "model_exists": model_exists,
            "model_loaded": self._model is not None,
            "model_error": self._model_error,
            "metadata": metadata,
        }

    def set_enabled(self, enabled: bool) -> None:
        self.config.enabled = bool(enabled)
        self.events.emit("SPEAKER_LOCK_CHANGED", enabled=self.config.enabled)

    def set_threshold(self, value: float) -> float:
        self.config.threshold = max(0.05, min(float(value), 0.95))
        self.events.emit("SPEAKER_THRESHOLD_CHANGED", threshold=self.config.threshold)
        return self.config.threshold

    def delete_profile(self) -> bool:
        removed = False
        for path in (self.profile_path, self.metadata_path):
            try:
                if path.exists():
                    path.unlink()
                    removed = True
            except OSError:
                pass
        if removed:
            self.events.emit("SPEAKER_PROFILE_DELETED", profile=self.config.profile_name)
        return removed

    def ensure_ready(self) -> dict[str, Any]:
        """
        Validate model file/hash and load it before asking the user to record
        enrollment samples. This prevents wasting five captures on a broken
        speaker backend.
        """
        try:
            self._load_model()
            return {
                "ok": True,
                "backend": "torchscript-campplus",
                "model": str(self.model_path),
                "sha256_verified": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "model": str(self.model_path),
            }

    def _load_model(self):
        if self._model is not None:
            return self._model

        if not self.model_path.exists():
            raise FileNotFoundError(
                "Modelo Voice Lock não encontrado. Executa .\\setup_voiceid.ps1."
            )

        actual_hash = self._sha256(self.model_path)
        expected_hash = self.config.model_sha256.lower().strip()
        if expected_hash and actual_hash.lower() != expected_hash:
            raise RuntimeError(
                "O hash SHA-256 do modelo Voice Lock não corresponde ao esperado. "
                "Apaga o ficheiro do modelo e volta a executar .\\setup_voiceid.ps1."
            )

        self.events.emit(
            "SPEAKER_MODEL_LOADING",
            backend="torchscript-campplus",
            device="cpu",
        )

        try:
            import torch

            model = torch.jit.load(str(self.model_path), map_location="cpu")
            model.eval()
            self._model = model
            self._model_error = None
            self.events.emit(
                "SPEAKER_MODEL_READY",
                backend="torchscript-campplus",
                device="cpu",
            )
            return model
        except Exception as exc:
            self._model_error = f"{type(exc).__name__}: {exc}"
            self.events.emit("SPEAKER_MODEL_FAILED", error=self._model_error)
            raise

    @staticmethod
    def _normalize_embedding(embedding: np.ndarray) -> np.ndarray:
        flat = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(flat))
        if norm <= 1e-12:
            raise ValueError("Speaker embedding has zero norm.")
        return flat / norm

    @staticmethod
    def _read_pcm_wav(path: str | Path):
        """
        Read the PCM WAV files generated by MicrophoneService without requiring
        torchaudio.load/TorchCodec.
        """
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if sample_width != 2:
            raise ValueError(
                f"Voice Lock espera PCM 16-bit WAV; sample width={sample_width}."
            )

        pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32)
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        pcm /= 32768.0
        return pcm, int(sample_rate)

    @staticmethod
    def _resample_torch(waveform, source_rate: int, target_rate: int = 16000):
        if int(source_rate) == int(target_rate):
            return waveform

        import torch.nn.functional as F

        length = waveform.numel()
        target_length = max(1, int(round(length * target_rate / source_rate)))
        x = waveform.reshape(1, 1, -1)
        x = F.interpolate(
            x,
            size=target_length,
            mode="linear",
            align_corners=False,
        )
        return x.reshape(-1)

    def _features_from_file(self, wav_path: str | Path):
        import torch
        import torchaudio.compliance.kaldi as Kaldi

        pcm, sample_rate = self._read_pcm_wav(wav_path)
        waveform = torch.from_numpy(pcm).to(torch.float32)
        waveform = self._resample_torch(waveform, sample_rate, 16000)

        if waveform.numel() < 1600:
            raise ValueError("A amostra de voz é demasiado curta para Voice Lock.")

        feat = Kaldi.fbank(
            waveform.unsqueeze(0),
            num_mel_bins=80,
            sample_frequency=16000,
            dither=0.0,
        )

        # Matches the 3D-Speaker FBank(mean_nor=True) preprocessing.
        feat = feat - feat.mean(0, keepdim=True)
        return feat

    def _embedding_from_file(self, wav_path: str | Path) -> np.ndarray:
        import torch

        model = self._load_model()
        feat = self._features_from_file(wav_path)

        with torch.inference_mode():
            output = model(feat.unsqueeze(0))

        if isinstance(output, (tuple, list)):
            output = output[-1]

        embedding = output.detach().cpu().numpy()
        return self._normalize_embedding(embedding)

    def enroll(self, wav_paths: list[str | Path]) -> dict[str, Any]:
        if len(wav_paths) < 3:
            return {
                "ok": False,
                "error": "NOT_ENOUGH_ENROLLMENT_SAMPLES",
                "message": "São necessárias pelo menos 3 amostras de voz.",
            }

        self._load_model()

        self.events.emit(
            "SPEAKER_ENROLLMENT_STARTED",
            samples=len(wav_paths),
            profile=self.config.profile_name,
        )

        embeddings = [self._embedding_from_file(path) for path in wav_paths]
        matrix = np.stack(embeddings, axis=0)
        centroid = self._normalize_embedding(matrix.mean(axis=0))

        similarities = matrix @ centroid
        mean_similarity = float(np.mean(similarities))
        min_similarity = float(np.min(similarities))

        np.savez_compressed(
            self.profile_path,
            embedding=centroid.astype(np.float32),
        )

        metadata = {
            "profile_name": self.config.profile_name,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "samples": len(wav_paths),
            "mean_enrollment_similarity": round(mean_similarity, 4),
            "min_enrollment_similarity": round(min_similarity, 4),
            "backend": "torchscript-campplus",
            "model": self.model_path.name,
            "raw_recordings_stored": False,
        }
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.events.emit(
            "SPEAKER_ENROLLMENT_FINISHED",
            profile=self.config.profile_name,
            samples=len(wav_paths),
            mean_similarity=round(mean_similarity, 4),
            min_similarity=round(min_similarity, 4),
        )

        return {
            "ok": True,
            "profile": self.config.profile_name,
            "samples": len(wav_paths),
            "mean_similarity": round(mean_similarity, 4),
            "min_similarity": round(min_similarity, 4),
            "threshold": self.config.threshold,
            "backend": "torchscript-campplus",
        }

    def verify(
        self,
        wav_path: str | Path,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "ok": True,
                "accepted": True,
                "bypassed": True,
                "reason": "speaker_lock_disabled",
            }

        if not self.enrolled():
            return {
                "ok": False,
                "accepted": False,
                "error": "SPEAKER_PROFILE_NOT_ENROLLED",
                "message": "O Voice Lock está ativo mas ainda não existe perfil de voz.",
            }

        if duration_seconds is not None and float(duration_seconds) < self.config.min_seconds:
            return {
                "ok": True,
                "accepted": False,
                "reason": "phrase_too_short",
                "duration_seconds": duration_seconds,
            }

        self.events.emit("SPEAKER_VERIFICATION_STARTED")
        sample = self._embedding_from_file(wav_path)

        stored = np.load(self.profile_path)
        owner = self._normalize_embedding(stored["embedding"])

        score = float(np.dot(owner, sample))
        accepted = score >= float(self.config.threshold)

        self.events.emit(
            "SPEAKER_VERIFICATION_FINISHED",
            accepted=accepted,
            score=round(score, 4),
            threshold=self.config.threshold,
        )

        return {
            "ok": True,
            "accepted": accepted,
            "score": round(score, 4),
            "threshold": self.config.threshold,
            "profile": self.config.profile_name,
            "backend": "torchscript-campplus",
        }
