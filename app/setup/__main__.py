from __future__ import annotations

import ctypes
import subprocess
import sys

from app.paths import frozen
from app.setup import install, ui
from app.setup.install import DEST, run, uninstall
from app.stack import admin

MB_INFO = 0x40
MB_WARN = 0x30
MB_ERROR = 0x10


def _box(text: str, kind: int = MB_INFO) -> None:
    """Сборка без консоли: без окна юзер не увидел бы ни ошибки, ни «готово»."""
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "Eblit", kind)
    except (OSError, AttributeError):
        pass


def _launch(args: list[str]) -> None:
    exe = DEST / "Eblit.exe"
    if "--no-launch" in args or not exe.is_file():
        return
    subprocess.Popen([str(exe)], cwd=str(DEST))


def _headless(args: list[str]) -> int:
    try:
        code = run()
    except (OSError, subprocess.SubprocessError) as exc:
        install.log(f"ошибка: {exc}")
        _box(f"Не установилось: {exc}\n\nЛог: {install.log_path()}", MB_ERROR)
        return 1
    if code == 0:
        _launch(args)
    return code


def _windowed(args: list[str]) -> int:
    def job(report):
        install.set_sink(report)
        try:
            return run()
        except (OSError, subprocess.SubprocessError) as exc:
            install.log(f"ошибка: {exc}")
            raise
        finally:
            install.set_sink(None)

    try:
        window = ui.Window(install.STEPS, log_file=install.log_path())
    except Exception as exc:  # окно не поднялось — установка важнее окна
        install.log(f"окно не открылось ({exc}) — ставлю без него")
        return _headless(args)
    code = window.run(job)
    if code == 0:
        _launch(args)
    return code


def _uninstall() -> int:
    code = uninstall()
    if frozen():
        if code == 0:
            _box("Eblit снят.")
        else:
            _box(f"Снято не всё. Лог: {install.log_path()}", MB_WARN)
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not admin.is_admin():
        if frozen():
            params = " ".join(admin._quote(x) for x in args)
        else:
            params = " ".join(admin._quote(x) for x in ["-m", "app.setup", *args])
        launched, code = admin.elevate_and_wait(sys.executable, params)
        if not launched:
            _box("Нужны права администратора.", MB_WARN)
            return 2
        return code

    if args[:1] == ["--uninstall"]:
        return _uninstall()
    if "--nogui" in args or not ui.available():
        return _headless(args)
    return _windowed(args)


if __name__ == "__main__":
    raise SystemExit(main())
