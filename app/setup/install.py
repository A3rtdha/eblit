from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
import zipfile
from datetime import datetime
from pathlib import Path

from app.setup.assets import WARP_MSI_URL, WEBVIEW2_URL, msiexec_args
from app.setup.fetch import download, latest_singbox_zip
from app.stack import autostart, nodes, singbox, teredo, warp
from app.stack.run import hidden, image_running, kill_image

DEST = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eblit"

# Sidecar'ы сборщика и его runtime-снимки. Даже если pack забыл вычистить dist —
# в Program Files они не должны оказаться.
_SKIP_PAYLOAD = {
    "lagom-nodes.json",
    "lagom-ips.json",
    "lagom-pick.json",
    "lagom-favorite.json",
    "lagom-probe.json",
    "lagom-sub.json",
    "eblit-power.json",
}

STEPS = (
    ("webview2", "WebView2"),
    ("warp", "Cloudflare WARP"),
    ("singbox", "sing-box"),
    ("copy", "файлы Eblit"),
    ("check", "проверка config.json"),
    ("warpcfg", "настройка WARP"),
    ("finish", "ярлыки и реестр"),
)

_SINK = None


def payload_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "payload"
    here = Path(__file__).resolve().parents[2] / "dist" / "Eblit"
    return here


def webview2_ok() -> bool:
    x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    roots = [
        x86 / "Microsoft" / "EdgeWebView" / "Application",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "EdgeWebView" / "Application",
    ]
    return any(p.is_dir() and any(p.iterdir()) for p in roots if p.exists())


def set_sink(fn) -> None:
    """Окно слушает шаги и строки лога. Без окна остаётся stdout и файл."""
    global _SINK
    _SINK = fn


def log_path() -> Path:
    return Path(tempfile.gettempdir()) / "eblit-setup.log"


def _log(line: str) -> None:
    if sys.stdout is not None:  # сборка без консоли: stdout нет, а лог нужен
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass
    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass
    if _SINK is not None:
        _SINK("log", "", line)


def log(line: str) -> None:
    """Публичная точка для __main__: причина должна попасть в тот же файл лога."""
    _log(line)


def _begin(key: str) -> None:
    if _SINK is not None:
        _SINK("step", key, "")
    _log(f"— {dict(STEPS).get(key, key)}")


def warp_ok() -> bool:
    """Рабочий warp-cli — повод не качать 60 МБ MSI поверх живого WARP."""
    try:
        return hidden([warp.cli_path(), "--version"], timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _stop_running() -> bool:
    """taskkill молча фейлится (нет прав, авторестарт) — проверяем, что процессы ушли."""
    kill_image("Eblit.exe")
    kill_image("sing-box.exe")
    if not singbox.wait_gone(tries=10):
        return False
    for _ in range(10):
        if not image_running("Eblit.exe"):
            return True
        time.sleep(0.3)
    return False


def _wait_warp_cli(tries: int = 30) -> bool:
    for _ in range(tries):
        hidden(["sc", "start", "CloudflareWARP"], timeout=15)
        cli = warp.cli_path()
        if hidden([cli, "--version"], timeout=10).returncode == 0:
            return True
        time.sleep(2)
    return False


def _shortcut(lnk: Path, target: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{str(lnk).replace(chr(39), chr(39)+chr(39))}');"
        f"$s.TargetPath='{str(target).replace(chr(39), chr(39)+chr(39))}';"
        f"$s.WorkingDirectory='{str(target.parent).replace(chr(39), chr(39)+chr(39))}';"
        "$s.Save()"
    )
    hidden(["powershell", "-NoProfile", "-Command", ps], timeout=20)
    if not lnk.is_file():
        raise OSError(f"не создан: {lnk}")


def _keep_existing_config(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return isinstance(data, dict) and nodes.has_user_vless(data)


def _copy_payload() -> None:
    src = payload_dir()
    if not (src / "Eblit.exe").is_file():
        raise OSError(f"нет payload Eblit: {src}")
    # Живой процесс держит файлы: копировать поверх — значит оставить половину установки.
    if not _stop_running():
        raise OSError("Eblit или sing-box не остановились — закрой их и повтори")
    DEST.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dest = DEST / item.name
        if item.name in _SKIP_PAYLOAD or item.name.startswith("_probe") or item.suffix == ".log":
            continue
        # Свои добавленные ноды бережём. Семёрка из утечки 1.0.0 — нет.
        if item.name == "config.json" and dest.is_file() and _keep_existing_config(dest):
            _log("config.json со своими нодами — не трогаю")
            continue
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


def _install_webview2(tmp: Path) -> None:
    if webview2_ok():
        _log("WebView2 уже есть")
        return
    _log("качаю WebView2…")
    setup = tmp / "MicrosoftEdgeWebview2Setup.exe"
    download(WEBVIEW2_URL, setup)
    r = hidden([str(setup), "/silent", "/install"], timeout=300)
    if r.returncode != 0 and not webview2_ok():
        raise OSError("WebView2 не встал")


def _install_warp(tmp: Path) -> None:
    if warp_ok():
        _log("WARP уже стоит")
        return
    _log("качаю актуальный WARP…")
    msi = tmp / "Cloudflare_WARP.msi"
    download(WARP_MSI_URL, msi, timeout=180)
    _log("ставлю WARP…")
    r = hidden(msiexec_args(msi), timeout=300)
    if r.returncode != 0 and not _wait_warp_cli(tries=5):
        raise OSError(f"WARP msiexec {r.returncode}")
    if not _wait_warp_cli():
        raise OSError("warp-cli не появился после установки")


def _install_singbox(tmp: Path) -> Path:
    bundled = payload_dir() / "sing-box.exe"
    try:
        _log("качаю актуальный sing-box…")
        zpath = tmp / "sing-box.zip"
        download(latest_singbox_zip(), zpath)
        with zipfile.ZipFile(zpath) as zf:
            for info in zf.infolist():
                if info.filename.endswith("sing-box.exe") and not info.is_dir():
                    data = zf.read(info)
                    out = tmp / "sing-box.exe"
                    out.write_bytes(data)
                    return out
        raise OSError("в zip нет sing-box.exe")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        # Обрезанный zip кидает BadZipFile, а не OSError: без этого установщик просто падал.
        if bundled.is_file() and bundled.stat().st_size > 0:
            _log(f"свежий sing-box не забрался ({exc}) — беру bundled")
            return bundled
        raise OSError(f"sing-box не скачался и bundled нет: {exc}") from exc


def _check_singbox() -> bool:
    exe = DEST / "sing-box.exe"
    cfg = DEST / "config.json"
    try:
        r = hidden([str(exe), "check", "-c", str(cfg)], timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"sing-box check: {exc}")
        return False
    if r.returncode == 0:
        return True
    _log(f"sing-box check: {(r.stderr or r.stdout or '').strip()[:200]}")
    return False


def _repair_empty_selector() -> bool:
    """Пустой LagomVPN → missing tags. Ноды не трогаем."""
    path = DEST / "config.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if not isinstance(cfg, dict) or not nodes.ensure_selector(cfg):
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    _log("починил пустой селектор LagomVPN — ноды на месте")
    return True


def _ensure_config_accepted(*, downloaded: bool) -> None:
    """Свежий sing-box может не принять наш config. Тогда лучше тот, с которым собрано."""
    if _check_singbox():
        return
    if _repair_empty_selector() and _check_singbox():
        return
    bundled = payload_dir() / "sing-box.exe"
    if downloaded and bundled.is_file() and bundled.stat().st_size > 0:
        _log("свежий sing-box не принял config.json — ставлю bundled")
        shutil.copy2(bundled, DEST / "sing-box.exe")
        if _check_singbox():
            return
    raise OSError("sing-box не принимает config.json")


def _configure_warp() -> None:
    _log("настройки WARP: MASQUE, proxy :40000")
    if not warp.ensure_registration():
        raise OSError("WARP registration new не прошёл")
    warp.configure()


def _register_uninstall() -> None:
    setup = DEST / "EblitSetup.exe"
    key = winreg.CreateKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Eblit",
    )
    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Eblit")
    winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Eblit")
    winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(DEST))
    if setup.is_file():
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{setup}" --uninstall')
    winreg.CloseKey(key)


def _unregister() -> None:
    try:
        winreg.DeleteKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Eblit",
        )
    except OSError:
        pass


def _lnk_paths() -> tuple[Path, Path]:
    start = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Eblit.lnk"
    desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop" / "Eblit.lnk"
    return start, desktop


def _shortcuts() -> None:
    exe = DEST / "Eblit.exe"
    start, desktop = _lnk_paths()
    _shortcut(start, exe)
    _shortcut(desktop, exe)


def _drop_shortcuts() -> None:
    for lnk in _lnk_paths():
        lnk.unlink(missing_ok=True)


def run() -> int:
    if sys.platform != "win32":
        _log("только Windows")
        return 1
    src = payload_dir()
    for need in ("Eblit.exe", "config.json"):
        if not (src / need).is_file():
            _log(f"сначала собери приложение: python -m app.pack  (нет {src / need})")
            return 1
    with tempfile.TemporaryDirectory(prefix="eblit-setup-") as raw:
        tmp = Path(raw)
        _begin("webview2")
        _install_webview2(tmp)
        _begin("warp")
        _install_warp(tmp)
        _begin("singbox")
        sb = _install_singbox(tmp)
        downloaded = sb != payload_dir() / "sing-box.exe"
        _begin("copy")
        _log(f"копирую Eblit → {DEST}")
        _copy_payload()
        shutil.copy2(sb, DEST / "sing-box.exe")
        if not (DEST / "config.json").is_file():
            raise OSError("после копирования нет config.json")
        _begin("check")
        _ensure_config_accepted(downloaded=downloaded)
        # Ключ снятия — до тяжёлых шагов: упавшая установка должна сниматься штатно.
        if getattr(sys, "frozen", False):
            shutil.copy2(sys.executable, DEST / "EblitSetup.exe")
        _register_uninstall()
        _begin("warpcfg")
        _configure_warp()
        _begin("finish")
        ok, why = teredo.disable()
        _log(why if ok else f"teredo: {why}")
        try:
            _shortcuts()
        except OSError as exc:  # без ярлыка приложение рабочее, установку не рушим
            _log(f"ярлык не создан: {exc}")
    _log("готово")
    return 0


def uninstall() -> int:
    if not _stop_running():
        _log("Eblit или sing-box ещё живы — часть файлов может остаться")
    _unregister()
    autostart.remove()
    warp.disconnect()
    warp.reset_mode()
    _drop_shortcuts()
    if DEST.exists():
        try:
            shutil.rmtree(DEST)
        except OSError as exc:
            _log(f"остались файлы в {DEST}: {exc}")
            return 1
    _log("снято")
    return 0
