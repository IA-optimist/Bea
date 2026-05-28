from __future__ import annotations

import json
import sys
from pathlib import Path


def count_mypy_errors(report: str) -> int:
    return sum(1 for line in report.splitlines() if ': error:' in line)


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write('usage: check_mypy_baseline.py <mypy-report.txt> <baseline.json>\n')
        return 2

    report_path = Path(sys.argv[1])
    baseline_path = Path(sys.argv[2])
    report = report_path.read_text(encoding='utf-8', errors='replace')
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    max_errors = int(baseline['max_errors'])
    current_errors = count_mypy_errors(report)

    if current_errors > max_errors:
        sys.stderr.write(
            f'mypy error budget exceeded: {current_errors} errors > baseline {max_errors}. '
            'Fix new errors or intentionally ratchet quality/mypy-baseline.json.\n'
        )
        return 1

    sys.stdout.write(f'mypy delta gate OK: {current_errors} errors <= baseline {max_errors}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
