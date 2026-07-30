"""WellbeingTracker characterization tests.

Mesure de regulation fonctionnelle, aucun ressenti revendique.
Uses temporary state files only; never writes data/wellbeing_state.json.
"""
from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.wellbeing_tracker as wb
from core.wellbeing_tracker import WellbeingTracker

TZ = ZoneInfo("Europe/Brussels")


@contextmanager
def _frozen_time(ts: float):
    old = wb.time.time
    wb.time.time = lambda: ts
    try:
        yield
    finally:
        wb.time.time = old


def _ts(year: int, month: int, day: int, hour: int) -> float:
    return datetime(year, month, day, hour, 0, tzinfo=TZ).timestamp()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _case(name: str, fn) -> bool:
    try:
        fn()
        ok = True
        detail = ""
    except AssertionError as exc:
        ok = False
        detail = str(exc)
    print(f"{name}: {'PASS' if ok else 'FAIL'}{('  ' + detail) if detail else ''}")
    return ok


def case_observe_deep_night_adds_date_and_is_idempotent(tmp: Path) -> None:
    path = tmp / "wb.json"
    tracker = WellbeingTracker(path=path)
    tracker.observe(now_ts=_ts(2026, 7, 9, 2))
    tracker.observe(now_ts=_ts(2026, 7, 9, 3))
    data = _read(path)
    assert data.get("night_dates") == ["2026-07-09"], data


def case_observe_daytime_does_not_add_date(tmp: Path) -> None:
    path = tmp / "wb.json"
    tracker = WellbeingTracker(path=path)
    tracker.observe(now_ts=_ts(2026, 7, 9, 14))
    assert not path.exists(), _read(path) if path.exists() else "created unexpectedly"


def case_two_nights_under_threshold_no_guidance(tmp: Path) -> None:
    path = tmp / "wb.json"
    tracker = WellbeingTracker(path=path)
    tracker.observe(now_ts=_ts(2026, 7, 8, 2))
    tracker.observe(now_ts=_ts(2026, 7, 9, 2))
    with _frozen_time(_ts(2026, 7, 10, 2)):
        assert tracker.render_guidance() == ""


def case_three_nights_emit_once_then_cooldown(tmp: Path) -> None:
    path = tmp / "wb.json"
    tracker = WellbeingTracker(path=path)
    tracker.observe(now_ts=_ts(2026, 7, 7, 2))
    tracker.observe(now_ts=_ts(2026, 7, 8, 2))
    tracker.observe(now_ts=_ts(2026, 7, 9, 2))
    with _frozen_time(_ts(2026, 7, 10, 2)):
        guidance = tracker.render_guidance()
        assert guidance != "", "expected guidance after 3 active nights"
        assert "nocturne" in guidance or "observation" in guidance, guidance
        assert tracker.render_guidance() == "", "cooldown should suppress immediate repeat"

def case_old_dates_are_pruned_from_threshold(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "wb.json"
    path.write_text(
        json.dumps({"night_dates": ["2026-07-01", "2026-07-08", "2026-07-09"]}),
        encoding="utf-8",
    )
    tracker = WellbeingTracker(path=path)
    with _frozen_time(_ts(2026, 7, 10, 2)):
        assert tracker.render_guidance() == ""


def case_absent_and_corrupt_files_are_graceful(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    absent = WellbeingTracker(path=tmp / "absent.json")
    assert absent._load() == {}
    corrupt_path = tmp / "corrupt.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")
    corrupt = WellbeingTracker(path=corrupt_path)
    assert corrupt._load() == {}
    corrupt.observe(now_ts=_ts(2026, 7, 9, 2))
    assert _read(corrupt_path).get("night_dates") == ["2026-07-09"]


def main() -> None:
    print("# WellbeingTracker characterization")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        results = [
            _case("observe_deep_night_adds_date_and_is_idempotent", lambda: case_observe_deep_night_adds_date_and_is_idempotent(tmp / "case1")),
            _case("observe_daytime_does_not_add_date", lambda: case_observe_daytime_does_not_add_date(tmp / "case2")),
            _case("two_nights_under_threshold_no_guidance", lambda: case_two_nights_under_threshold_no_guidance(tmp / "case3")),
            _case("three_nights_emit_once_then_cooldown", lambda: case_three_nights_emit_once_then_cooldown(tmp / "case4")),
            _case("old_dates_are_pruned_from_threshold", lambda: case_old_dates_are_pruned_from_threshold(tmp / "case5")),
            _case("absent_and_corrupt_files_are_graceful", lambda: case_absent_and_corrupt_files_are_graceful(tmp / "case6")),
        ]
    ok = all(results)
    print(f"overall: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()