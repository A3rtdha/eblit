"""Build the pinned Windows core without installing Go or changing user settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_file(path: Path, expected: str) -> None:
    if sha256(path) != expected:
        raise ValueError(f"checksum mismatch: {path.name}")


def download_verified(url: str, path: Path, expected: str) -> None:
    if path.is_file():
        verify_file(path, expected)
        return
    if not url.startswith("https://"):
        raise ValueError("build downloads require HTTPS")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "eblit-core-build"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("build download redirected outside HTTPS")
            with temporary.open("wb") as target:
                shutil.copyfileobj(response, target, 1024 * 1024)
        verify_file(temporary, expected)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def extract_zip(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            target = (root / item.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError("archive entry leaves extraction directory")
        archive.extractall(root)


def build_environment(work_dir: Path, toolchain: Path, manifest: dict) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GOROOT": str(toolchain),
            "GOTOOLCHAIN": "local",
            "GOENV": "off",
            "GOWORK": "off",
            "GOFLAGS": "-mod=readonly",
            "GOPROXY": "https://proxy.golang.org",
            "GOSUMDB": "sum.golang.org",
            "GONOPROXY": "",
            "GONOSUMDB": "",
            "GOPRIVATE": "",
            "GOVCS": "*:off",
            "GOTELEMETRY": "off",
            "GOMODCACHE": str(work_dir / "module-cache"),
            "GOCACHE": str(work_dir / "build-cache"),
            "GOPATH": str(work_dir / "gopath"),
            "GOMAXPROCS": "2",
            **manifest["environment"],
        }
    )
    return environment


def run(command: list[str], *, source: Path, environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=source, env=environment, check=True)


def check_config(binary: Path, directory: Path) -> None:
    config = {
        "log": {"disabled": True},
        "outbounds": [
            {
                "type": "vless",
                "tag": "xhttp-check",
                "server": "127.0.0.1",
                "server_port": 443,
                "uuid": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                "tls": {"enabled": True, "server_name": "test.example"},
                "transport": {
                    "type": "xhttp",
                    "path": "/xh",
                    "host": "test.example",
                    "mode": "auto",
                    "x_padding_bytes": {"from": 100, "to": 1000},
                },
            },
            {
                "type": "hysteria2",
                "tag": "hy2-check",
                "server": "127.0.0.1",
                "server_port": 443,
                "password": "test-password",
                "obfs": {"type": "salamander", "password": "test-obfs"},
                "idle_timeout": "30s",
                "keep_alive_period": "10s",
                "tls": {
                    "enabled": True,
                    "server_name": "test.example",
                    "alpn": ["h3"],
                    "certificate_sha256": ["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="],
                },
            },
        ],
        "route": {"final": "xhttp-check"},
    }
    path = directory / "core-check.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    subprocess.run([str(binary), "check", "-c", str(path)], cwd=directory, check=True)


def build(work_dir: Path, output: Path) -> dict:
    if sys.platform != "win32":
        raise OSError("the pinned core build requires Windows amd64")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    patch_path = HERE / manifest["patch"]["file"]
    test_path = HERE / manifest["handshake_test"]["file"]
    protocol_test = HERE / manifest["protocol_test"]["file"]
    verify_file(patch_path, manifest["patch"]["sha256"])
    verify_file(test_path, manifest["handshake_test"]["sha256"])
    verify_file(protocol_test, manifest["protocol_test"]["sha256"])
    work_dir = work_dir.resolve()
    output = output.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    source_archive = work_dir / "source.tar.gz"
    toolchain_archive = work_dir / "go1.27.0.windows-amd64.zip"
    download_verified(manifest["source"]["url"], source_archive, manifest["source"]["sha256"])
    download_verified(manifest["toolchain"]["url"], toolchain_archive, manifest["toolchain"]["sha256"])

    extraction = Path(tempfile.mkdtemp(prefix="build-", dir=work_dir))
    with tarfile.open(source_archive) as archive:
        archive.extractall(extraction / "source", filter="data")
    source = extraction / "source" / manifest["source"]["directory"]
    extract_zip(toolchain_archive, extraction / "toolchain")
    toolchain = extraction / "toolchain" / "go"
    go = str(toolchain / "bin" / "go.exe")
    environment = build_environment(work_dir, toolchain, manifest)
    version = subprocess.check_output([go, "version"], env=environment, text=True).strip()
    if version != manifest["toolchain"]["version_output"]:
        raise ValueError("Go toolchain version mismatch")
    for name, expected in manifest["source"]["module_files"].items():
        verify_file(source / name, expected)

    run(["git", "apply", "--check", str(patch_path)], source=source, environment=environment)
    run(["git", "apply", str(patch_path)], source=source, environment=environment)
    shutil.copyfile(test_path, source / "common" / "tls" / "eblit_pinned_certificate_test.go")
    tags = ",".join(manifest["tags"])
    run([go, "mod", "verify"], source=source, environment=environment)
    run(
        [go, "test", "-p=2", "-tags", tags, "-ldflags=-checklinkname=0",
         "-count=1", "-run", "^TestEblitCertificatePin", "./common/tls"],
        source=source,
        environment=environment,
    )
    binary = extraction / "sing-box.exe"
    run(
        [go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-tags", tags,
         "-ldflags", manifest["ldflags"], "-o", str(binary), "./cmd/sing-box"],
        source=source,
        environment=environment,
    )
    run([go, "mod", "verify"], source=source, environment=environment)
    for name, expected in manifest["source"]["module_files"].items():
        verify_file(source / name, expected)
    check_config(binary, extraction)
    subprocess.run([sys.executable, str(protocol_test), "--binary", str(binary)], cwd=extraction, check=True)
    version_output = subprocess.check_output([str(binary), "version"], text=True)
    if version_output.splitlines()[0] != "sing-box version " + manifest["version"]:
        raise ValueError("built core version mismatch")
    metadata = {
        **manifest,
        "binary_sha256": sha256(binary),
        "binary_size": binary.stat().st_size,
        "version_output": version_output,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".part")
    try:
        shutil.copyfile(binary, temporary_output)
        temporary_output.replace(output)
    finally:
        temporary_output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".build.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return {"output": str(output), "version": manifest["version"], "sha256": metadata["binary_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.work_dir, arguments.output)), flush=True)


if __name__ == "__main__":
    main()
