import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import scripts.synthetic_auto_runner as runner


def test_next_wait_seconds_resumes_from_persisted_state():
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "runner_state.json"
        now = datetime(2026, 7, 20, 14, 0, 0)
        state_path.write_text(
            json.dumps(
                {"last_scan_time": (now - timedelta(hours=23, minutes=30)).isoformat()}
            )
        )

        wait_seconds = runner._next_wait_seconds(state_path, 86400, now)

        assert wait_seconds == 1800


def test_next_wait_seconds_has_no_initial_delay_on_cold_start():
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "runner_state.json"
        now = datetime(2026, 7, 20, 14, 0, 0)

        wait_seconds = runner._next_wait_seconds(state_path, 86400, now)

        assert wait_seconds == 0


def test_initial_cycle_runs_immediately_even_with_prior_state():
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "runner_state.json"
        now = datetime(2026, 7, 20, 14, 0, 0)
        state_path.write_text(
            json.dumps({"last_scan_time": (now - timedelta(minutes=10)).isoformat()})
        )

        wait_seconds = runner._wait_before_next_scan(
            cycle=0,
            state_path=state_path,
            interval_seconds=86400,
            now=now,
        )

        assert wait_seconds == 0


def test_default_scan_interval_is_five_minutes():
    assert runner.DEFAULT_SCAN_INTERVAL_MINUTES == 5.0
