"""Train the bundled demo model (backend/services/ml/demo_model.json.z).

The Vercel function does not ship scikit-learn, so the demo garden attaches a
Random Forest trained here, offline, on the demo simulator's own data. Run after
changing the demo soil model or the feature list:

    python tools/make_demo_model.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    from backend.app import create_app
    from backend.db import SessionLocal
    from backend.services import demo
    from backend.services.ml import forest_runtime
    from backend.services.ml.train import train_model
    from backend.timeutil import utcnow

    out = os.path.join(ROOT, "backend", "services", "ml", "demo_model.json.z")
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app({"DATABASE_URL": f"sqlite:///{tmp}/demo.db", "GK_DEMO_MODE": "true", "SECRET_KEY": "make-demo-model"})
        with app.app_context():
            # Seed without the bundled model, then train like the real weekly job.
            if os.path.exists(out):
                os.rename(out, out + ".bak")
            try:
                demo.ensure_seeded(utcnow())
                SessionLocal().commit()
                model = train_model(utcnow(), notes="demo model", n_estimators=100)
            finally:
                if os.path.exists(out + ".bak"):
                    os.rename(out + ".bak", out)
            forest = forest_runtime.unpack(model.artifact)
            meta = dict(model.metadata_json or {})
            meta["version"] = "rf-demo-" + model.model_version.split("-", 1)[1]
            meta["held_out"] = meta.get("held_out", [])[:120]
            forest["meta"] = meta
            blob = zlib.compress(json.dumps(forest, separators=(",", ":")).encode(), 9)
            with open(out, "wb") as fh:
                fh.write(blob)
            m = meta["metrics"]
            print(f"wrote {out} ({len(blob) / 1024:.0f} KB): rows {meta['rows']}, MAE {m['mae']:.3f} vs {m['baseline_mae']:.3f}, "
                  f"RMSE {m['rmse']:.3f} vs {m['baseline_rmse']:.3f}, beats baseline: {meta['beats_baseline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
