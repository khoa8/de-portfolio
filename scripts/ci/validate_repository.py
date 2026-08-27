#!/usr/bin/env python3
"""Validate repository hygiene and local Markdown links without external I/O."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".example",
    ".gitignore",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {"AGENTS.md", "Dockerfile", ".gitignore"}
PLACEHOLDERS = {
    "",
    "change_me",
    "changeme",
    "replace_me",
    "password",
    "redacted",
}
FORBIDDEN_EXACT = {
    ".DS_Store",
    "airflow/.env",
    "airflow/config/airflow.cfg",
    "airflow/config/simple_auth_manager_passwords.json.generated",
}
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SECRET_PATTERNS = {
    "private-key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "google-api-key": re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    "oauth-token": re.compile(r"ya29\.[A-Za-z0-9_-]+"),
    "github-token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "slack-token": re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    "credential-uri": re.compile(
        r"(?:postgres(?:ql)?|mysql|mssql)://[^\s/:]+:[^\s@]+@",
        re.IGNORECASE,
    ),
}
JSON_SECRET = re.compile(
    r'''["'](?:[^"']*(?:password|secret|token|api[_-]?key|fernet)[^"']*)["']'''
    r'''\s*:\s*["']([^"']*)["']''',
    re.IGNORECASE,
)
ENV_SECRET = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|FERNET_KEY|API_KEY)\s*="
    r"\s*(.*)\s*$"
)
YAML_SECRET = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|FERNET_KEY|API_KEY)\s*:"
    r"\s*(.*)\s*$"
)
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")


def repository_paths() -> list[Path]:
    command = [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    output = subprocess.check_output(command, cwd=REPO_ROOT)
    return [REPO_ROOT / item for item in output.decode().split("\0") if item]


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_text_candidate(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def secret_literal_is_safe(value: str) -> bool:
    normalized = value.strip().strip('"\'').strip()
    lowered = normalized.lower()
    return (
        lowered in PLACEHOLDERS
        or lowered.startswith(
            ("${", "$", "<", "test-", "example", "dummy", "replace_")
        )
        or lowered.startswith("cat ")
        or lowered.startswith("re.compile(")
    )


def heading_slugs(markdown: Path) -> set[str]:
    slugs: set[str] = set()
    for line in markdown.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = match.group(1).strip().lower()
        heading = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE)
        heading = re.sub(r"\s+", "-", heading)
        heading = re.sub(r"-+", "-", heading).strip("-")
        slugs.add(heading)
    return slugs


def validate() -> list[str]:
    failures: list[str] = []
    paths = repository_paths()
    markdown_files: list[Path] = []

    for path in paths:
        rel = relative(path)
        parts = set(path.relative_to(REPO_ROOT).parts)
        if (
            rel in FORBIDDEN_EXACT
            or parts & FORBIDDEN_PARTS
            or rel.startswith("airflow/logs/")
            or rel.startswith("airflow/checkpoints/")
            or path.suffix.lower() in {".log", ".pyc"}
        ):
            failures.append(f"{rel}: forbidden generated or secret-bearing path")
            continue
        if path.name == ".env" or (path.suffix == ".env" and path.name != ".env.example"):
            failures.append(f"{rel}: tracked/unignored environment file")
            continue
        if not path.is_file() or not is_text_candidate(path):
            continue

        raw = path.read_bytes()
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"{rel}: expected UTF-8 text")
            continue

        if not text.endswith("\n"):
            failures.append(f"{rel}: missing final newline")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if re.search(r"[ \t]+$", line):
                failures.append(f"{rel}:{line_number}: trailing whitespace")

        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{rel}: credential pattern ({category})")

        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in (JSON_SECRET, ENV_SECRET, YAML_SECRET):
                match = pattern.search(line)
                if match and not secret_literal_is_safe(match.group(1)):
                    failures.append(
                        f"{rel}:{line_number}: non-placeholder secret assignment"
                    )

        if path.suffix.lower() == ".md":
            markdown_files.append(path)

    for markdown in markdown_files:
        text = markdown.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part, _, anchor = target.partition("#")
            resolved = (markdown.parent / unquote(path_part)).resolve()
            rel = relative(markdown)
            if not resolved.exists():
                failures.append(f"{rel}: broken local link ({target})")
                continue
            if anchor and resolved.suffix.lower() == ".md":
                if unquote(anchor).lower() not in heading_slugs(resolved):
                    failures.append(f"{rel}: missing Markdown anchor ({target})")

    return failures


def main() -> int:
    failures = validate()
    if failures:
        print("Repository validation: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Repository validation: PASS")
    print("Checked tracked and untracked source for links, whitespace, artifacts, and secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
