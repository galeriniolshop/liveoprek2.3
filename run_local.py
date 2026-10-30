"""Jalankan app asli; companion uploader dimulai oleh app pada port 8502."""
import os
from pathlib import Path
import sys
from streamlit.web import cli
root = Path(__file__).resolve().parent
os.environ.setdefault("LIVEOPREK_DATA", str(root / "data"))
sys.argv = ["streamlit", "run", str(root / "app.py"), "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
raise SystemExit(cli.main())
