from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_PHONE_PRIVATE_REACHES: dict[str, set[str]] = {
    "skills/regression/ios_settings/scrolling.py": {
        "_page_drag_xy",
    },
    "skills/regression/ios_settings/trace.py": {
        "_trace",
    },
}


def _iter_production_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("glassbox", "skills"):
        for path in (REPO_ROOT / root_name).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if path.name == "phone.py" or path.name.startswith("test_") or "/smoke/" in rel:
                continue
            files.append(path)
    return files


def _phone_private_reaches(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=path.as_posix())
    symbols: set[str] = set()
    for scope in _iter_scopes(tree):
        symbols.update(_phone_private_reaches_in_scope(scope))
    return symbols


def _iter_scopes(tree: ast.AST) -> list[ast.AST]:
    scopes: list[ast.AST] = [tree]
    scopes.extend(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    )
    return scopes


def _phone_private_reaches_in_scope(scope: ast.AST) -> set[str]:
    phone_aliases = _phone_aliases(scope)
    symbols: set[str] = set()
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.Attribute)
            and _is_phone_like_expr(node.value, phone_aliases)
            and node.attr.startswith("_")
        ):
            symbols.add(node.attr)
            continue
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr"}
            and len(node.args) >= 2
            and _is_phone_like_expr(node.args[0], phone_aliases)
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value.startswith("_")
        ):
            continue
        symbols.add(node.args[1].value)
    return symbols


def _phone_aliases(scope: ast.AST) -> set[str]:
    aliases = {"phone"}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for arg in (*scope.args.args, *scope.args.posonlyargs, *scope.args.kwonlyargs):
            if arg.arg.endswith("_phone"):
                aliases.add(arg.arg)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(scope):
            if not isinstance(node, ast.Assign) or not _is_phone_like_expr(node.value, aliases):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def _is_phone_like_expr(node: ast.AST, aliases: set[str] | None = None) -> bool:
    aliases = aliases or {"phone"}
    if isinstance(node, ast.Name):
        return node.id in aliases or node.id.endswith("_phone")
    if isinstance(node, ast.Attribute):
        return node.attr in {"phone", "_phone"} or node.attr.endswith("_phone")
    return False


@pytest.mark.smoke
def test_phone_private_reach_inventory_is_explicit():
    found = {
        path.relative_to(REPO_ROOT).as_posix(): symbols
        for path in _iter_production_python_files()
        if (symbols := _phone_private_reaches(path))
    }

    assert found == ALLOWED_PHONE_PRIVATE_REACHES


@pytest.mark.smoke
def test_perception_does_not_import_effectors():
    offenders: list[str] = []
    for path in (REPO_ROOT / "glassbox" / "perception").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=path.as_posix())
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("glassbox.effectors"):
                        offenders.append(path.relative_to(REPO_ROOT).as_posix())
                continue
            if module and module.startswith("glassbox.effectors"):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []
