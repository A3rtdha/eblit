from __future__ import annotations

import base64
import ctypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.stack.run import CREATE_NO_WINDOW


_RUN_COPY = r"""
$ErrorActionPreference = 'Stop'
$setup = $env:EBLIT_UNINSTALL_COPY
$stage = Split-Path -LiteralPath $setup
$log = $env:EBLIT_UNINSTALL_LOG
try {
    foreach ($originId in $env:EBLIT_UNINSTALL_ORIGIN_IDS.Split(',')) {
        $origin = Get-Process -Id $originId -ErrorAction SilentlyContinue
        if ($origin -and $origin.Path -eq $env:EBLIT_UNINSTALL_SOURCE) {
            Wait-Process -InputObject $origin -Timeout 30
        }
    }
    $worker = Start-Process -FilePath $setup -ArgumentList '--uninstall' -PassThru -Wait
    exit $worker.ExitCode
} catch {
    Add-Content -LiteralPath $log -Value $_ -Encoding UTF8 -ErrorAction SilentlyContinue
    $shell = New-Object -ComObject WScript.Shell
    $shell.Popup("Снято не всё. Лог: $log", 0, 'Eblit', 48) | Out-Null
    exit 1
} finally {
    try {
        Remove-Item -LiteralPath $setup -Force
        Remove-Item -LiteralPath $stage
    } catch {
        Add-Content -LiteralPath $log -Value $_ -Encoding UTF8 -ErrorAction SilentlyContinue
    }
}
"""


def _system_powershell() -> Path:
    path = ctypes.create_unicode_buffer(260)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(path, len(path))
    if not 0 < size < len(path):
        raise OSError("не найден системный каталог Windows")
    return Path(path.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def relaunch_from_copy(executable: Path, install_dir: Path, log_path: Path) -> bool:
    install_dir = install_dir.resolve()
    executable = executable.resolve()
    if not executable.is_relative_to(install_dir):
        return False

    powershell = _system_powershell()
    # Временная копия наследует права Program Files.
    stage = Path(tempfile.mkdtemp(prefix=".eblit-uninstall-", dir=install_dir.parent))
    setup = stage / executable.name
    try:
        shutil.copy2(executable, setup)
        # У onefile оба процесса держат исходный exe: загрузчик и Python.
        env = {
            **os.environ,
            "EBLIT_UNINSTALL_COPY": str(setup),
            "EBLIT_UNINSTALL_SOURCE": str(executable),
            "EBLIT_UNINSTALL_ORIGIN_IDS": f"{os.getpid()},{os.getppid()}",
            "EBLIT_UNINSTALL_LOG": str(log_path),
            "PYINSTALLER_RESET_ENVIRONMENT": "1",
        }
        command = base64.b64encode(_RUN_COPY.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(
            [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            cwd=install_dir.parent,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        setup.unlink(missing_ok=True)
        stage.rmdir()
        raise
    return True
