"""Command line tools (Makefile targets call these).

  python -m backend.cli create-tables
  python -m backend.cli create-manager --username ana --name "Ana Cruz"
  python -m backend.cli register-device --id gk-node-01
  python -m backend.cli rotate-device-key --id gk-node-01
  python -m backend.cli train
  python -m backend.cli run-jobs
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gardekalinga")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-tables", help="create all tables (dev / first deploy without Alembic)")
    m = sub.add_parser("create-manager", help="create a manager account")
    m.add_argument("--username", required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--password", help="omit to be asked (recommended)")
    d = sub.add_parser("register-device", help="register the ESP32 and print its secret once")
    d.add_argument("--id", default="gk-node-01")
    d.add_argument("--name", default="Box B field controller")
    r = sub.add_parser("rotate-device-key")
    r.add_argument("--id", default="gk-node-01")
    t = sub.add_parser("train", help="train the Random Forest now (needs requirements-ml.txt)")
    t.add_argument("--if-requested", action="store_true", help="only when a manager queued a retrain or the schedule is due")
    sub.add_parser("run-jobs", help="run every due scheduled job once")
    args = p.parse_args(argv)

    from .app import create_app
    from .db import Base, SessionLocal, get_engine

    app = create_app()
    with app.app_context():
        s = SessionLocal()
        if args.cmd == "create-tables":
            from . import models  # noqa: F401

            Base.metadata.create_all(get_engine())
            print("Tables are ready.")
        elif args.cmd == "create-manager":
            from .models import User
            from .security import MIN_PASSWORD_LEN, hash_password
            from .services.audit import audit
            from .timeutil import utcnow

            pw = args.password or getpass.getpass("Password (10+ characters): ")
            if len(pw) < MIN_PASSWORD_LEN:
                print(f"Password must have at least {MIN_PASSWORD_LEN} characters.", file=sys.stderr)
                return 2
            uname = args.username.strip().lower()
            if s.scalars(select(User).where(User.username == uname)).first():
                print("That username already exists.", file=sys.stderr)
                return 2
            u = User(full_name=args.name, username=uname, password_hash=hash_password(pw), role="manager", created_at=utcnow(),
                     is_active=True, theme="auto")
            s.add(u)
            s.flush()
            audit("user.create_cli", f"user:{u.user_id}", None, {"username": uname, "role": "manager"})
            s.commit()
            print(f"Manager '{uname}' created.")
        elif args.cmd == "register-device":
            from .blueprints.admin import register_device
            from .services.audit import audit

            dev, secret = register_device(args.id, args.name)
            audit("device.register_cli", f"device:{dev.device_id}")
            s.commit()
            print(f"Device {dev.device_id} registered.\n\nDEVICE SECRET (shown once, enter it in the controller setup page):\n{secret}\n")
        elif args.cmd == "rotate-device-key":
            from .device_auth import encrypt_secret, new_device_secret
            from .models import Device
            from .services.audit import audit
            from .timeutil import utcnow

            dev = s.get(Device, args.id)
            if dev is None:
                print("No such device.", file=sys.stderr)
                return 2
            secret = new_device_secret()
            dev.key_encrypted, dev.key_rotated_at = encrypt_secret(secret), utcnow()
            audit("device.rotate_key_cli", f"device:{dev.device_id}")
            s.commit()
            print(f"New secret for {dev.device_id} (shown once):\n{secret}")
        elif args.cmd == "train":
            from .models import AppState, MLModel
            from .services.jobs import _phase_sync
            from .services.ml.train import TrainingUnavailable, train_model
            from .timeutil import to_manila, utcnow

            now = utcnow()
            if args.if_requested:
                req = s.get(AppState, "retrain_request")
                weekly = to_manila(now).weekday() == 6
                first = s.scalar(select(func.count()).select_from(MLModel)) == 0
                if not (req or weekly or first):
                    print("Nothing to do.")
                    return 0
            try:
                model = train_model(now, notes="cli")
            except TrainingUnavailable as e:
                print(f"Not trained: {e}")
                return 0
            req = s.get(AppState, "retrain_request")
            if req is not None:
                s.delete(req)
            _phase_sync(now)
            s.commit()
            print(f"Trained {model.model_version}: MAE {model.mae:.3f} (baseline {model.baseline_mae:.3f}), "
                  f"RMSE {model.rmse:.3f} (baseline {model.baseline_rmse:.3f}). Active: {model.is_active}")
        elif args.cmd == "run-jobs":
            from .services.jobs import JOBS, run_due
            from .timeutil import utcnow

            print(run_due(utcnow(), tuple(JOBS)))
            s.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
