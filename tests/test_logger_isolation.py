"""Subprocesses must be able to keep both log handlers out of production."""

import os
from pathlib import Path
import subprocess
import sys


def test_log_directory_override_redirects_both_files(tmp_path):
    log_dir = tmp_path / "isolated_logs"
    env = os.environ.copy()
    env["MERID_LOG_DIR"] = str(log_dir)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    code = (
        "from utils import logger; "
        "print(logger.LOG_FILE); print(logger.PRODUCTION_LOG_FILE); "
        "logger.get_logger('isolation_test').warning('isolated log probe')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == [
        str(log_dir / "full.log"), str(log_dir / "server_output.log")
    ]
    assert "isolated log probe" in (log_dir / "full.log").read_text(encoding="utf-8")
    assert "isolated log probe" in (log_dir / "server_output.log").read_text(encoding="utf-8")
