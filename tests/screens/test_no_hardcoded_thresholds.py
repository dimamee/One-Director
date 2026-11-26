"""No numeric thresholds in the screens code: they live in configuration only.

docs/model-card.md §8, docs/threat-model.md T-04. The demo values are in
``demo_config.toml`` (not Python) and are marked "DEMO — не для продакшна".
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCREENS = ROOT / "src" / "one_director" / "screens"

# Literals that are definitions, not tunable thresholds: 0 and 1 (identities,
# "single" bidder), 2 (a pair, the median of an even count).
DEFINITIONAL_INTS = {0, 1, 2}
# Technical constants (no screening meaning), allowed only as these module-level names.
TECHNICAL_CONSTANTS = {
    "DECIMAL_PRECISION",  # digits of the Decimal context
    "QUANTUM",  # rounding step of stored ratios
    "DIGEST_PREFIX_LEN",  # config hash prefix inside rule_version
    "RULE_VERSION_MAX_LEN",  # flags.rule_version is VARCHAR(32)
}


def _technical_nodes(tree: ast.Module) -> set[int]:
    allowed: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if names & TECHNICAL_CONSTANTS:
            allowed.update(id(child) for child in ast.walk(value))
    return allowed


def test_screens_code_has_no_numeric_thresholds() -> None:
    sources = sorted(SCREENS.glob("*.py"))
    assert sources
    offenders = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        technical = _technical_nodes(tree)
        for node in ast.walk(tree):
            if id(node) in technical:
                continue
            if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
                value = node.value
                if isinstance(value, float | complex) or (
                    isinstance(value, int) and value not in DEFINITIONAL_INTS
                ):
                    offenders.append(f"{path.name}:{node.lineno}: {value!r}")
            # Integer arguments are covered above; a decimal string ("0.02") would hide a threshold.
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None)) == "Decimal"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                offenders.append(f"{path.name}:{node.lineno}: Decimal({node.args[0].value!r})")
    assert not offenders, "numeric literals in screens code:\n" + "\n".join(offenders)


def test_demo_config_is_the_only_place_with_demo_values() -> None:
    data_files = {path.name for path in SCREENS.iterdir() if path.suffix in {".toml", ".json"}}
    assert data_files == {"demo_config.toml"}
