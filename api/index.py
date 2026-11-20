"""Vercel Python entry point. vercel.json rewrites every /api/* request here; Flask
sees the original path, so the routes in backend/blueprints match as written."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app  # noqa: E402

app = create_app()
