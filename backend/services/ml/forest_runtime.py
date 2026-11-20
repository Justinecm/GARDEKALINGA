"""Pure-Python inference for a trained scikit-learn RandomForestRegressor.

The trainer (train.py, needs scikit-learn) exports every tree's arrays
(children_left, children_right, feature, threshold, value) into a compressed
JSON artifact stored in ml_models.artifact. This module walks those trees, which
gives exactly sklearn's prediction (mean of the trees' leaf values) without
shipping scikit-learn, SciPy and NumPy inside the Vercel function bundle.
"""
from __future__ import annotations

import json
import struct
import zlib
from typing import Any

LEAF = -1


def _f32(x: float) -> float:
    # sklearn trees compare float32 inputs against float64 thresholds.
    return struct.unpack("f", struct.pack("f", float(x)))[0]


def pack(forest: dict[str, Any]) -> bytes:
    return zlib.compress(json.dumps(forest, separators=(",", ":")).encode(), 9)


def unpack(blob: bytes) -> dict[str, Any]:
    return json.loads(zlib.decompress(blob).decode())


class Forest:
    def __init__(self, data: dict[str, Any]):
        self.features: list[str] = data["features"]
        self.trees: list[tuple[list[int], list[int], list[int], list[float], list[float]]] = [
            (t["l"], t["r"], t["f"], t["t"], t["v"]) for t in data["trees"]
        ]

    def predict_one(self, x: dict[str, float]) -> float:
        vec = [_f32(x[name]) for name in self.features]
        total = 0.0
        for left, right, feat, thr, val in self.trees:
            node = 0
            while left[node] != LEAF:
                # sklearn sends a sample left when x[feature] <= threshold
                node = left[node] if vec[feat[node]] <= thr[node] else right[node]
            total += val[node]
        return total / len(self.trees)


_CACHE: dict[str, Forest] = {}


def load(version: str, blob: bytes) -> Forest:
    f = _CACHE.get(version)
    if f is None:
        if len(_CACHE) > 3:
            _CACHE.clear()
        f = _CACHE[version] = Forest(unpack(blob))
    return f
