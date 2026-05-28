from __future__ import annotations

import sys
from pathlib import Path


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if ';' in line:
            line = line.split(';', 1)[0].strip()
        if '==' not in line:
            raise ValueError(f'{path}: unpinned requirement: {raw}')
        name, version = line.split('==', 1)
        name = name.split('[', 1)[0].lower().strip()
        pins[name] = version.strip()
    return pins


def main(argv: list[str]) -> int:
    req_path = Path(argv[1]) if len(argv) > 1 else Path('requirements.txt')
    lock_path = Path(argv[2]) if len(argv) > 2 else Path('requirements.lock')
    req_pins = _pins(req_path)
    lock_pins = _pins(lock_path)

    errors: list[str] = []
    for name, version in sorted(req_pins.items()):
        locked = lock_pins.get(name)
        if locked != version:
            errors.append(f'{name}: requirements.txt={version}, requirements.lock={locked or "MISSING"}')

    if errors:
        sys.stderr.write('requirements lock drift detected:\n')
        for err in errors:
            sys.stderr.write(f'  - {err}\n')
        sys.stderr.write('Regenerate with: bash scripts/generate_requirements_lock.sh\n')
        return 1

    sys.stdout.write(f'requirements lock drift check OK: {len(req_pins)} direct pins match {lock_path}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
