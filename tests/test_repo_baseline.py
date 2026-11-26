"""Guards for the Phase 0 security baseline of the repository itself.

These tests check configuration, not business logic: they fail if someone
removes a protection that the rest of the project relies on.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import one_director

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "CLAUDE.md",
    "README.md",
    "SECURITY.md",
    "TASK.md",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "requirements.in",
    "requirements.txt",
    "requirements-dev.in",
    "requirements-dev.txt",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".claude/settings.json",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    "docs/threat-model.md",
    "docs/data-protection.md",
    "docs/llm-safety.md",
    "docs/scraping-policy.md",
    "docs/access-control.md",
    "docs/incident-response.md",
    "docs/model-card.md",
    "docs/glossary-uz-ru.md",
    "specs/schema.md",
    "specs/api-contract.md",
    *[
        f"specs/agents/{name}.md"
        for name in (
            "01-data",
            "02-registry",
            "03-screens",
            "04-graph",
            "05-model",
            "06-report-llm",
            "07-backend",
            "08-frontend",
            "09-reviewer",
            "10-pitch",
        )
    ],
    "src/one_director/__init__.py",
    *[
        f"src/one_director/{pkg}/__init__.py"
        for pkg in ("security", "data", "registry", "screens", "graph", "model", "report", "api")
    ],
    "app/README.md",
    "tests/fixtures/README.md",
    "data/README.md",
    "notebooks/README.md",
]

REQUIRED_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "APP_SECRET_KEY",
    "PSEUDONYM_SALT",
    "DEMO_MODE",
    "ALLOWED_ORIGINS",
}


def test_package_is_importable() -> None:
    assert one_director.__version__ == "0.0.0"


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_required_file_exists_and_is_not_empty(relative_path: str) -> None:
    path = ROOT / relative_path
    assert path.is_file(), f"missing: {relative_path}"
    assert path.stat().st_size > 0, f"empty: {relative_path}"


def test_env_example_has_only_empty_secrets() -> None:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    assert values.keys() >= REQUIRED_ENV_KEYS
    assert values.pop("DEMO_MODE") == "true", "DEMO_MODE must default to true"
    non_empty = {key for key, value in values.items() if value}
    assert not non_empty, f".env.example must not contain values: {sorted(non_empty)}"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "secrets/key.txt",
        "data/raw/lots.json",
        "data/processed/lots.parquet",
        ".claude/settings.local.json",
        "notebooks/.ipynb_checkpoints/x.ipynb",
    ],
)
def test_sensitive_paths_are_git_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not ignored by .gitignore"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize("path", [".env.example", "data/README.md", ".claude/settings.json"])
def test_shared_files_are_not_git_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1, f"{path} must be tracked"


def test_claude_settings_deny_secret_access() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    permissions = settings["permissions"]
    assert permissions["disableBypassPermissionsMode"] == "disable"
    for rule in ("Read(./.env)", "Read(./.env.*)", "Read(./secrets/**)", "Read(./data/raw/**)"):
        assert rule in permissions["deny"], f"missing deny rule {rule}"


@pytest.mark.parametrize("lock_file", ["requirements.txt", "requirements-dev.txt"])
def test_lock_files_are_pinned_with_hashes(lock_file: str) -> None:
    text = (ROOT / lock_file).read_text(encoding="utf-8")
    requirements = re.findall(r"^([A-Za-z0-9._-]+)(\S*) \\$", text, flags=re.MULTILINE)
    assert requirements, f"no requirements found in {lock_file}"
    unpinned = [name for name, spec in requirements if not spec.startswith("==")]
    assert not unpinned, f"unpinned packages in {lock_file}: {unpinned}"
    blocks = re.split(r"\n(?=[A-Za-z0-9])", text.split("\n\n", 1)[-1])
    without_hash = [b.split("=", 1)[0] for b in blocks if "==" in b and "--hash=sha256:" not in b]
    assert not without_hash, f"packages without hashes in {lock_file}: {without_hash}"


def test_ci_permissions_are_read_only() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n  contents: read$", ci, flags=re.MULTILINE)
    assert "write" not in ci.split("jobs:", 1)[0], "top-level permissions must be read-only"
