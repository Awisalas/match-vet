from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from dataclasses import asdict, dataclass
from importlib import metadata, resources
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from matchvet.artifacts import inspect_artifacts
from matchvet.store import (
    InspectionStatus,
    default_database_path,
    inspect_store,
    termux_private_root,
)


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    expected: str
    actual: str


def apply_runtime_limits() -> None:
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"


def _load_baseline() -> tuple[dict[str, Any], str]:
    baseline_bytes = resources.files("matchvet").joinpath("baseline.json").read_bytes()
    loaded: object = json.loads(baseline_bytes)
    if not isinstance(loaded, dict):
        raise ValueError("The packaged environment baseline must be a JSON object.")
    return loaded, hashlib.sha256(baseline_bytes).hexdigest()


def _run(*command: str) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError, subprocess.TimeoutExpired, OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _package_version(package: str) -> str | None:
    return _run("dpkg-query", "-W", "-f=${Version}", package)


def _python_package_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _check(identifier: str, expected: str, actual: str | None) -> Check:
    rendered_actual = actual if actual is not None else "MISSING"
    status = "PASS" if rendered_actual == expected else "FAIL"
    return Check(identifier, status, expected, rendered_actual)


def _command_check(command: str) -> Check:
    actual = shutil.which(command)
    return Check(
        id=f"command:{command}",
        status="PASS" if actual is not None else "FAIL",
        expected="available",
        actual=actual or "MISSING",
    )


def _getprop(name: str) -> str | None:
    return _run("getprop", name)


def _repository_root() -> Path | None:
    candidates = (Path.cwd(), Path(__file__).resolve().parents[2])
    for candidate in candidates:
        discovered = _run("git", "-C", str(candidate), "rev-parse", "--show-toplevel")
        if discovered is not None:
            return Path(discovered).resolve()
    return None


def _git_commit(project_root: Path | None) -> str:
    if project_root is None:
        return "UNKNOWN"
    return _run("git", "-C", str(project_root), "rev-parse", "HEAD") or "UNKNOWN"


def _storage_environment(project_root: Path | None) -> dict[str, str]:
    home = Path(os.environ.get("TERMUX__HOME", Path.home())).resolve()
    prefix = Path(os.environ.get("TERMUX__PREFIX", os.environ.get("PREFIX", ""))).resolve()
    shared_link = home / "storage" / "shared"
    shared = shared_link.resolve() if shared_link.exists() else shared_link
    return {
        "private_home": str(home),
        "private_prefix": str(prefix),
        "project_root": str(project_root) if project_root is not None else "UNKNOWN",
        "shared_storage": str(shared),
    }


def _storage_check(identifier: str, path: str) -> Check:
    candidate = Path(path)
    accessible = candidate.is_dir() and os.access(candidate, os.R_OK | os.W_OK | os.X_OK)
    return Check(
        id=f"storage:{identifier}",
        status="PASS" if accessible else "FAIL",
        expected="accessible",
        actual="accessible" if accessible else "MISSING_OR_INACCESSIBLE",
    )


def _sanitize_repository_line(line: str) -> str:
    parts = line.split()
    sanitized: list[str] = []
    for part in parts:
        if "://" not in part:
            sanitized.append(part)
            continue
        parsed = urlsplit(part)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        sanitized.append(urlunsplit((parsed.scheme, host, parsed.path, "", "")))
    return " ".join(sanitized)


def _apt_sources() -> list[str]:
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    apt_root = prefix / "etc" / "apt"
    source_files = [apt_root / "sources.list"]
    source_files.extend(sorted((apt_root / "sources.list.d").glob("*.list")))
    sources: list[str] = []
    for source_file in source_files:
        try:
            lines = source_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        sources.extend(
            _sanitize_repository_line(line.strip())
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        )
    return sources


def _dpkg_inventory() -> list[dict[str, str]]:
    output = _run("dpkg-query", "-W", "-f=${Package}\t${Version}\n")
    if output is None:
        return []
    inventory: list[dict[str, str]] = []
    for line in output.splitlines():
        package, separator, version = line.partition("\t")
        if separator:
            inventory.append({"package": package, "version": version})
    return inventory


def _sha256_file(path: Path) -> str | None:
    try:
        contents = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(contents).hexdigest()


def _manifest_file_records(project_root: Path | None) -> dict[str, dict[str, str]]:
    paths = (
        ".python-version",
        "environment/termux-packages.lock",
        "pyproject.toml",
        "uv.lock",
    )
    records: dict[str, dict[str, str]] = {}
    for relative_path in paths:
        digest = None if project_root is None else _sha256_file(project_root / relative_path)
        records[relative_path] = {
            "status": "PRESENT" if digest is not None else "MISSING",
            "sha256": digest or "UNKNOWN",
        }
    return records


def _termux_lock_matches(project_root: Path | None, baseline: dict[str, Any]) -> bool:
    if project_root is None:
        return False
    try:
        lines = (project_root / "environment" / "termux-packages.lock").read_text(encoding="utf-8")
    except OSError:
        return False
    locked = dict(
        line.split("=", maxsplit=1)
        for line in lines.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    return bool(locked == baseline["termux_packages"])


def _python_manifests_match(project_root: Path | None, baseline: dict[str, Any]) -> bool:
    if project_root is None:
        return False
    try:
        python_version = (project_root / ".python-version").read_text(encoding="utf-8").strip()
        with (project_root / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
        with (project_root / "uv.lock").open("rb") as lock_file:
            lock = tomllib.load(lock_file)
    except OSError, tomllib.TOMLDecodeError:
        return False

    locked_versions = {
        package.get("name"): package.get("version")
        for package in lock.get("package", [])
        if isinstance(package, dict)
    }
    return (
        python_version == baseline["python"]["version"]
        and pyproject.get("project", {}).get("requires-python") == "==3.14.*"
        and pyproject.get("tool", {}).get("uv") == {"package": True, "python-downloads": "never"}
        and all(
            locked_versions.get(package) == version
            for package, version in baseline["python_packages"].items()
        )
    )


def _availability_check(identifier: str, available: bool) -> Check:
    return Check(
        id=identifier,
        status="PASS" if available else "FAIL",
        expected="available",
        actual="available" if available else "MISSING_OR_INVALID",
    )


def build_report(store_path: Path | None = None) -> dict[str, Any]:
    baseline, baseline_digest = _load_baseline()
    baseline_python = baseline["python"]
    baseline_termux = baseline["termux"]
    baseline_android = baseline["android"]
    project_root = _repository_root()

    termux_package_versions = {
        package: _package_version(package) for package in baseline["termux_packages"]
    }
    python_package_versions = {
        package: _python_package_version(package) for package in baseline["python_packages"]
    }

    python_environment = {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "termux_package_version": termux_package_versions["python"] or "MISSING",
    }
    termux_environment = {
        "version": os.environ.get("TERMUX_VERSION", "UNKNOWN"),
        "release": os.environ.get("TERMUX_APK_RELEASE", "UNKNOWN"),
    }
    android_environment = {
        "api_level": _getprop("ro.build.version.sdk") or "UNKNOWN",
        "version": _getprop("ro.build.version.release") or "UNKNOWN",
    }
    thread_limits = {name: os.environ.get(name, "UNSET") for name in baseline["thread_limits"]}
    storage_environment = _storage_environment(project_root)
    manifest_files = _manifest_file_records(project_root)
    apt_sources = _apt_sources()
    dpkg_inventory = _dpkg_inventory()
    git_commit = _git_commit(project_root)
    store_inspection = inspect_store(
        store_path or default_database_path(),
        private_root=termux_private_root(),
    )
    artifact_inspection = inspect_artifacts(
        store_path or default_database_path(),
        private_root=termux_private_root(),
    )

    checks = [
        _check(
            "python-implementation",
            str(baseline_python["implementation"]),
            python_environment["implementation"],
        ),
        _check("python-version", str(baseline_python["version"]), python_environment["version"]),
        _check("architecture", str(baseline["architecture"]), platform.machine()),
        _check("platform", str(baseline["platform"]), sysconfig.get_platform()),
        _check("termux-version", str(baseline_termux["version"]), termux_environment["version"]),
        _check("termux-release", str(baseline_termux["release"]), termux_environment["release"]),
        _check("android-version", str(baseline_android["version"]), android_environment["version"]),
        _check("android-api", str(baseline_android["api_level"]), android_environment["api_level"]),
    ]
    checks.extend(_command_check(command) for command in baseline["commands"])
    checks.extend(
        _check(f"termux-package:{package}", str(expected), termux_package_versions[package])
        for package, expected in baseline["termux_packages"].items()
    )
    if store_inspection.status is not InspectionStatus.NOT_CONFIGURED:
        checks.append(
            _availability_check(
                "store:integrity",
                store_inspection.status is InspectionStatus.HEALTHY,
            )
        )
    if store_inspection.status is not InspectionStatus.NOT_CONFIGURED:
        checks.append(_availability_check("artifacts:integrity", artifact_inspection.healthy))
    checks.extend(
        _check(f"python-package:{package}", str(expected), python_package_versions[package])
        for package, expected in baseline["python_packages"].items()
    )
    checks.extend(
        _check(f"thread-limit:{name}", str(expected), thread_limits[name])
        for name, expected in baseline["thread_limits"].items()
    )
    checks.extend(
        _storage_check(name, storage_environment[name])
        for name in ("private_home", "private_prefix", "project_root", "shared_storage")
    )
    checks.extend(
        (
            _availability_check("capture:termux-repositories", bool(apt_sources)),
            _availability_check("capture:dpkg-inventory", bool(dpkg_inventory)),
            _availability_check("capture:git-commit", len(git_commit) == 40),
            _availability_check(
                "environment-manifest:termux-lock",
                _termux_lock_matches(project_root, baseline),
            ),
            _availability_check(
                "environment-manifest:python-locks",
                _python_manifests_match(project_root, baseline),
            ),
        )
    )

    status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    manifest_status = (
        "PASS"
        if all(
            check.status == "PASS"
            for check in checks
            if check.id.startswith("environment-manifest:")
        )
        else "FAIL"
    )
    report: dict[str, Any] = {
        "schema_version": baseline["schema_version"],
        "status": status,
        "mode": "RESEARCH_ONLY",
        "baseline": baseline["id"],
        "checks": [asdict(check) for check in checks],
        "environment_manifest": {
            "status": manifest_status,
            "baseline_sha256": baseline_digest,
            "files": manifest_files,
        },
        "store": {
            "path": store_inspection.path,
            "status": store_inspection.status,
            "schema_version": store_inspection.schema_version,
            "applied_migrations": store_inspection.applied_migrations,
            "integrity": store_inspection.integrity,
            "foreign_key_violations": store_inspection.foreign_key_violations,
            "pragmas": store_inspection.pragmas,
            "limits": store_inspection.limits,
            "issues": [asdict(issue) for issue in store_inspection.issues],
        },
        "artifacts": asdict(artifact_inspection),
        "environment": {
            "python": python_environment,
            "architecture": platform.machine(),
            "platform": sysconfig.get_platform(),
            "termux": termux_environment,
            "android": android_environment,
            "kernel": platform.release(),
            "termux_repositories": apt_sources,
            "termux_packages": termux_package_versions,
            "python_packages": python_package_versions,
            "dpkg_inventory": dpkg_inventory,
            "thread_limits": thread_limits,
            "storage": storage_environment,
            "git_commit": git_commit,
        },
        "capabilities": {
            "authoritative_store": store_inspection.status,
            "active_run": "NONE",
            "source_reachability": "NOT_IMPLEMENTED_T06",
        },
    }
    if store_inspection.status is InspectionStatus.RECOVERY_REQUIRED:
        report["error"] = {
            "code": store_inspection.issues[0].code,
            "summary": store_inspection.issues[0].message,
            "recovery_command": f"matchvet doctor --store {shlex.quote(store_inspection.path)}",
        }
    elif status == "FAIL":
        report["error"] = {
            "code": "MV-PREFLIGHT-ENVIRONMENT_MISMATCH",
            "summary": "The current Termux environment does not match the pinned baseline.",
            "recovery_command": "scripts/bootstrap-termux.sh",
        }
    return report


def render_human_report(report: dict[str, Any]) -> str:
    lines = [
        "MatchVet doctor",
        f"Status: {report['status']}",
        f"Mode: {report['mode']}",
        f"Baseline: {report['baseline']}",
    ]
    for check in report["checks"]:
        lines.append(
            f"[{check['status']}] {check['id']}: expected {check['expected']}; "
            f"actual {check['actual']}"
        )
    store = report["store"]
    if store["status"] == InspectionStatus.NOT_CONFIGURED:
        lines.append("Store: not configured")
    elif store["status"] == InspectionStatus.HEALTHY:
        lines.append(
            f"Store: healthy; schema {store['schema_version']}; "
            f"migrations {len(store['applied_migrations'])}"
        )
    else:
        lines.append(f"Store: read-only recovery required; {store['issues'][0]['code']}")
    artifacts = report["artifacts"]
    if store["status"] == InspectionStatus.HEALTHY:
        if all(
            not artifacts[name] for name in ("missing", "corrupt", "orphans", "malformed_manifests")
        ):
            lines.append("Artifacts: healthy")
        else:
            lines.append(
                "Artifacts: issues; "
                + ", ".join(
                    f"{name}={len(artifacts[name])}"
                    for name in (
                        "missing",
                        "corrupt",
                        "orphans",
                        "unreferenced",
                        "malformed_manifests",
                    )
                    if artifacts[name]
                )
            )
    lines.append("Active run: none")
    if report["status"] == "PASS":
        lines.append("Next action: matchvet")
    else:
        lines.append("Recovery: scripts/bootstrap-termux.sh")
    return "\n".join(lines) + "\n"
