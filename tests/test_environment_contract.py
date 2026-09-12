from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        loaded: object = tomllib.load(source)
    assert isinstance(loaded, dict)
    return loaded


def test_termux_package_lock_matches_the_packaged_doctor_baseline() -> None:
    baseline = json.loads(
        (PROJECT_ROOT / "src" / "matchvet" / "baseline.json").read_text(encoding="utf-8")
    )
    locked_packages = dict(
        line.split("=", maxsplit=1)
        for line in (PROJECT_ROOT / "environment" / "termux-packages.lock")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    )

    assert baseline["termux_packages"] == locked_packages


def test_project_declares_only_the_approved_direct_python_dependencies() -> None:
    project = load_toml(PROJECT_ROOT / "pyproject.toml")

    assert project["build-system"]["requires"] == ["setuptools==80.9.0"]
    assert project["project"]["requires-python"] == "==3.14.*"
    assert project["project"]["dependencies"] == ["requests==2.34.2"]
    assert project["dependency-groups"]["dev"] == [
        "mypy==1.18.2",
        "pytest==9.1.1",
    ]
    assert project["tool"]["uv"] == {
        "package": True,
        "python-downloads": "never",
    }


def test_uv_lock_contains_the_pinned_build_runtime_and_test_packages() -> None:
    lock = load_toml(PROJECT_ROOT / "uv.lock")
    versions = {
        package["name"]: package.get("version")
        for package in lock["package"]
        if isinstance(package, dict)
    }

    assert versions["requests"] == "2.34.2"
    assert versions["pytest"] == "9.1.1"
    assert versions["mypy"] == "1.18.2"
