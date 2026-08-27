# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Static checks for the arrange/act/assert integration-test contract."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

INTEGRATION_DIR = Path(__file__).parent / "integration"
RESOURCE_MUTATORS = frozenset(
    {
        "add_model",
        "config",
        "consume",
        "deploy",
        "integrate",
        "model_config",
        "offer",
        "remove_application",
    }
)
PHASES = ("Arrange", "Act", "Assert")
_MARKER_RE = re.compile(r"^#\s*(Arrange|Act|Assert|Teardown)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    """One integration-test structure violation."""

    path: Path
    line: int
    message: str

    def format(self) -> str:
        """Return a stable, grep-friendly diagnostic."""
        return f"{self.path}:{self.line}: {self.message}"


def _is_pytest_fixture(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function is decorated with ``pytest.fixture``."""
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield top-level functions that represent integration tests."""
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            and not _is_pytest_fixture(node)
        ):
            yield node


def _markers(source: str, start: int, end: int) -> dict[str, list[int]]:
    """Collect phase comments in a function's source range."""
    result: dict[str, list[int]] = {name: [] for name in (*PHASES, "Teardown")}
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT or not start <= token.start[0] <= end:
            continue
        match = _MARKER_RE.match(token.string)
        if match:
            result[match.group(1).capitalize()].append(token.start[0])
    return result


def _phase(line: int, markers: dict[str, list[int]]) -> str | None:
    """Return the latest declared phase at a source line."""
    candidates = [(row, name) for name, rows in markers.items() for row in rows if row <= line]
    return max(candidates, default=(0, None))[1]


def _mutator_name(call: ast.Call) -> str | None:
    """Return a recognized direct Juju resource mutator name."""
    if isinstance(call.func, ast.Attribute) and call.func.attr in RESOURCE_MUTATORS:
        return call.func.attr
    return None


def _marker_violations(
    path: Path,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    markers: dict[str, list[int]],
) -> list[Violation]:
    """Validate marker count and ordering for one test."""
    violations: list[Violation] = []
    marker_rows = []
    for phase in PHASES:
        rows = markers[phase]
        if len(rows) != 1:
            violations.append(
                Violation(path, function.lineno, f"{function.name}: expected one # {phase} marker")
            )
        else:
            marker_rows.append(rows[0])
    if len(marker_rows) == len(PHASES) and marker_rows != sorted(marker_rows):
        violations.append(
            Violation(path, function.lineno, f"{function.name}: phase markers are out of order")
        )
    return violations


def _node_violations(
    path: Path,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    markers: dict[str, list[int]],
) -> list[Violation]:
    """Validate source nodes against their declared test phase."""
    violations: list[Violation] = []
    act_row = markers["Act"][0] if len(markers["Act"]) == 1 else function.lineno
    end_lineno = function.end_lineno or function.lineno
    assert_row = markers["Assert"][0] if len(markers["Assert"]) == 1 else end_lineno + 1
    for node in ast.walk(function):
        if isinstance(node, ast.Assert) and node.lineno < act_row:
            violations.append(
                Violation(path, node.lineno, f"{function.name}: assertion appears before # Act")
            )
        if not isinstance(node, ast.Call):
            continue
        mutator = _mutator_name(node)
        current_phase = _phase(node.lineno, markers)
        if mutator and current_phase not in {"Act", "Teardown"}:
            violations.append(
                Violation(
                    path,
                    node.lineno,
                    f"{function.name}: direct Juju {mutator} must be in # Act or # Teardown; "
                    "put arrangement in ensure_*",
                )
            )
        if (
            isinstance(node.func, ast.Name)
            and node.func.id.startswith("ensure_")
            and node.lineno > act_row
        ):
            violations.append(
                Violation(
                    path, node.lineno, f"{function.name}: ensure_* call must be in # Arrange"
                )
            )
        if node.lineno > assert_row and mutator and current_phase != "Teardown":
            violations.append(
                Violation(
                    path,
                    node.lineno,
                    f"{function.name}: Juju {mutator} write appears after # Assert",
                )
            )
    return violations


def _is_cleanup_call(call: ast.Call, mutator: str) -> bool:
    """Return whether a fixture mutation is an explicit cleanup operation."""
    if mutator == "remove_application":
        return True
    if mutator == "config":
        return any(keyword.arg == "reset" for keyword in call.keywords)
    if mutator == "model_config":
        if not call.args or not isinstance(call.args[0], ast.Dict):
            return False
        return all(
            isinstance(value, ast.Constant) and value.value == "" for value in call.args[0].values
        )
    return False


def _fixture_violations(path: Path) -> list[Violation]:
    """Ensure fixture bodies do not hide non-idempotent resource setup."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[Violation] = []
    for function in (
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_pytest_fixture(node)
    ):
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            mutator = _mutator_name(node)
            if mutator and not _is_cleanup_call(node, mutator):
                violations.append(
                    Violation(
                        path,
                        node.lineno,
                        f"{function.name}: fixture must delegate Juju {mutator} to ensure_*",
                    )
                )
    return violations


def analyze_file(path: Path) -> list[Violation]:
    """Analyze one integration test module using only its source and AST."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[Violation] = []
    for function in _functions(tree):
        end_lineno = function.end_lineno or function.lineno
        markers = _markers(source, function.lineno, end_lineno)
        violations.extend(_marker_violations(path, function, markers))
        violations.extend(_node_violations(path, function, markers))
    return violations


def analyze() -> list[Violation]:
    """Analyze every integration test module in lexical order."""
    violations: list[Violation] = []
    for path in sorted(INTEGRATION_DIR.glob("test_*.py")):
        violations.extend(analyze_file(path))
        violations.extend(_fixture_violations(path))
    violations.extend(_fixture_violations(INTEGRATION_DIR / "conftest.py"))
    return violations


def test_integration_tests_follow_aaa() -> None:
    """Keep every integration test visibly arranged as Arrange/Act/Assert."""
    violations = analyze()
    assert not violations, "\n".join(violation.format() for violation in violations)
