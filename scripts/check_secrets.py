"""Fail CI when repository files contain high-confidence secret formats."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "staticfiles",
}
EXCLUDED_FILES = {Path(__file__).resolve(), PROJECT_ROOT / "uv.lock"}
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    "Stripe live key": re.compile(rb"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}\b"),
    "generic credential": re.compile(
        rb"(?i:\b[a-z_][a-z0-9_]*(?:password|passwd|secret|api_key|token))"
        rb"\s*[:=]\s*(?:[rubf]{0,2})[\"']"
        rb"(?=[^\"'\r\n]{20,}[\"'])(?=[^\"'\r\n]*[A-Z])"
        rb"(?=[^\"'\r\n]*[a-z])(?=[^\"'\r\n]*[0-9])"
        rb"(?=[^\"'\r\n]*[!@#$%^&*])[^\"'\r\n]+[\"']"
    ),
}


def repository_files() -> list[Path]:
    """Return tracked and non-ignored files so local checks cover pending work."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    paths = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = (PROJECT_ROOT / raw_path.decode("utf-8")).resolve()
        if path in EXCLUDED_FILES or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.is_file():
            paths.append(path)
    return paths


def find_secrets(path: Path) -> list[str]:
    """Return names of high-confidence patterns found in a reasonably sized file."""
    if path.stat().st_size > 5 * 1024 * 1024:
        return []
    content = path.read_bytes()
    if b"\0" in content:
        return []
    return [
        name for name, pattern in SECRET_PATTERNS.items() if pattern.search(content)
    ]


def main() -> int:
    """Print actionable findings without echoing the secret value."""
    findings: list[tuple[Path, str]] = []
    for path in repository_files():
        findings.extend((path, name) for name in find_secrets(path))
    if findings:
        for path, name in findings:
            print(
                f"Potential {name} in {path.relative_to(PROJECT_ROOT)}", file=sys.stderr
            )
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
