from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = REPO_ROOT / "programs"

BUILD_TOOL_COMMAND_RE = re.compile(
    r"^\s*"
    r"(?:(?:env|command)\s+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=(?:\S+|'[^']*'|\"[^\"]*\")\s+)*"
    r"(?:(?:\./|\.\./|.*/)?configure|cmake|make|ninja|meson|scons|spack|"
    r"cargo\s+build|go\s+build|pip\s+install|"
    r"nvcc|nvc(?:\+\+)?|mpicc|mpicxx|gcc|g\+\+|clang(?:\+\+)?|cc|c\+\+|"
    r"fc|f77|f90|flang|ifort|ifx)\b"
)

BUILD_OPTION_ASSIGN_RE = re.compile(
    r"(^|\s)(?:export\s+)?"
    r"(?:CC|CXX|FC|F77|F90|CPP|CPPFLAGS|CFLAGS|CXXFLAGS|FCFLAGS|FFLAGS|LDFLAGS|LIBS)"
    r"\s*="
)


def _script_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((lineno, line))
    return lines


def _program_scripts(name: str) -> list[Path]:
    return sorted(PROGRAMS_DIR.glob(f"*/{name}"))


def test_build_scripts_do_not_depend_on_profile_or_estimate_scripts():
    offenders: list[str] = []
    for path in _program_scripts("build.sh"):
        for lineno, line in _script_lines(path):
            if "profile.sh" in line or "estimate.sh" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert offenders == []


def test_profile_and_estimate_scripts_do_not_drive_build_configuration():
    offenders: list[str] = []
    for path in [*_program_scripts("profile.sh"), *_program_scripts("estimate.sh")]:
        for lineno, line in _script_lines(path):
            if BUILD_TOOL_COMMAND_RE.search(line) or BUILD_OPTION_ASSIGN_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert offenders == []
