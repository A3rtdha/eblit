"""Build dist/Eblit/Eblit.exe and copy sidecar files. No bats."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _singbox() -> Path | None:
    local = ROOT / "sing-box.exe"
    if local.is_file() and local.stat().st_size > 0:
        return local
    found = shutil.which("sing-box")
    if not found:
        return None
    real = Path(found).resolve()
    if real.is_file() and real.stat().st_size > 0:
        return real
    return None


def main() -> int:
    spec = ROOT / "eblit.spec"
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", str(spec), "-y"],
        cwd=str(ROOT),
    )
    dist = ROOT / "dist" / "Eblit"
    if not (dist / "Eblit.exe").is_file():
        print(f"нет {dist / 'Eblit.exe'}", file=sys.stderr)
        return 1
    cfg = ROOT / "config.json"
    if not cfg.is_file():
        print(f"нет {cfg}", file=sys.stderr)
        return 1
    # Живой config.json содержит личные vless/IP сборщика — в установщик уходит чистый.
    from app.stack import nodes

    shipped = nodes.sanitize_for_ship(json.loads(cfg.read_text(encoding="utf-8")))
    (dist / "config.json").write_text(json.dumps(shipped, indent=2) + "\n", encoding="utf-8")
    # Прогон приложения из dist оставляет здесь пики/хосты/логи — их слать нельзя.
    for pattern in ("lagom-*.json", "_probe*.json", "*.log", "eblit-power.json", "eblit-first.json"):
        for stray in dist.glob(pattern):
            stray.unlink()
    shipped_vless = [o for o in shipped.get("outbounds", []) if o.get("type") == "vless"]
    print(f"payload config: {len(shipped_vless)} vless")
    if shipped_vless:
        print("sanitize оставил vless — установщик не собираю", file=sys.stderr)
        return 1
    sb = _singbox()
    if sb is None:
        print("нет sing-box.exe — положи его рядом с Eblit.exe", file=sys.stderr)
    else:
        shutil.copy2(sb, dist / "sing-box.exe")
    setup_spec = ROOT / "setup.spec"
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", str(setup_spec), "-y"],
        cwd=str(ROOT),
    )
    setup = ROOT / "dist" / "EblitSetup.exe"
    if not setup.is_file():
        print(f"нет {setup}", file=sys.stderr)
        return 1
    print(dist)
    print(setup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
