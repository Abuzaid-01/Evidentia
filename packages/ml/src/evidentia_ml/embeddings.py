"""SigLIP image + text embeddings in one vector space.

This replaces Cloudinary Visual Search (Enterprise-only, Media-Library-only): we embed the same
`ev_ai` rendition the vision models saw, and at query time embed the user's text with the SigLIP text
tower, so "workers laying a blue pipe in a trench" finds matching photos even when no caption says so.

Vectors are L2-normalised, so cosine distance in pgvector (`<=>`) is the right metric.
"""

from __future__ import annotations

import hashlib
import io
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_images(self, images: list[bytes]) -> list[list[float]]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def match_probability(self, cosine_similarity: float) -> float: ...


def _normalise(matrix: np.ndarray) -> list[list[float]]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32).tolist()


class SiglipEmbedder:
    """Lazy-loading, thread-safe SigLIP wrapper (Hugging Face transformers)."""

    def __init__(self, model_name: str, *, device: str = "cpu", dim: int = 768) -> None:
        self.model_name = model_name
        self.dim = dim
        self._device = device
        self._lock = threading.Lock()
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import torch  # heavy imports only when embeddings are actually used
            from transformers import AutoModel, AutoProcessor

            torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
            processor = AutoProcessor.from_pretrained(self.model_name)
            model = AutoModel.from_pretrained(self.model_name).to(self._device).eval()
            self._processor, self._model = processor, model

    @staticmethod
    def _features(output: object) -> object:
        # transformers returns a tensor (v4) or a model output with pooler_output (v5+)
        return getattr(output, "pooler_output", output)

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        self._load()
        import torch
        from PIL import Image

        pil = [Image.open(io.BytesIO(data)).convert("RGB") for data in images]
        with self._lock, torch.inference_mode():
            inputs = self._processor(images=pil, return_tensors="pt").to(self._device)  # type: ignore[misc]
            feats = self._features(self._model.get_image_features(**inputs))  # type: ignore[union-attr]
        return self._check(_normalise(feats.float().cpu().numpy()))  # type: ignore[union-attr]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._load()
        import torch

        with self._lock, torch.inference_mode():
            # SigLIP was trained with fixed-length (64) padded text
            inputs = self._processor(  # type: ignore[misc]
                text=[t or " " for t in texts],
                padding="max_length",
                truncation=True,
                max_length=64,
                return_tensors="pt",
            ).to(self._device)
            feats = self._features(self._model.get_text_features(**inputs))  # type: ignore[union-attr]
        return self._check(_normalise(feats.float().cpu().numpy()))  # type: ignore[union-attr]

    def match_probability(self, cosine_similarity: float) -> float:
        """SigLIP's own calibrated text-image match probability: sigmoid(scale * sim + bias)."""
        self._load()
        scale = float(self._model.logit_scale.exp())  # type: ignore[union-attr]
        bias = float(self._model.logit_bias)  # type: ignore[union-attr]
        return float(1.0 / (1.0 + np.exp(-(scale * cosine_similarity + bias))))

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(
                f"{self.model_name} produced {len(vectors[0])}-d vectors but EMBEDDING_DIM={self.dim}"
            )
        return vectors


class HashEmbedder:
    """Deterministic, dependency-free embedder for tests. Texts sharing words get similar vectors;
    an image's vector equals the text vector of its bytes decoded as words (so tests can steer it)."""

    model_name = "hash-embedder-v1"

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode()).digest()
            for i in range(0, 16, 2):
                vec[int.from_bytes(digest[i : i + 2], "big") % self.dim] += 1.0
        if not vec.any():
            vec[0] = 1.0
        return _normalise(vec[None, :])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        return [self._vector(data.decode("utf-8", "ignore")) for data in images]

    def match_probability(self, cosine_similarity: float) -> float:
        return max(0.0, min(1.0, cosine_similarity))


@lru_cache
def get_embedder(model_name: str, device: str, dim: int) -> Embedder:
    if model_name == HashEmbedder.model_name:
        return HashEmbedder(dim)
    return SiglipEmbedder(model_name, device=device, dim=dim)
