"""AST-based helpers for enforcing domain module boundaries."""

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

PUBLIC_BOUNDARIES = frozenset({"events", "policies", "selectors", "services"})
TARGET_PUBLIC_SYMBOLS = {
    "core.persistence": frozenset({"UUIDTimestampedModel"}),
}
EDGE_PUBLIC_SYMBOLS: dict[tuple[str, str], dict[str, frozenset[str]]] = {}


@dataclass(frozen=True)
class ImportTarget:
    """A module import, optionally retaining its imported symbol."""

    module: str
    symbol: str | None = None

    @property
    def path(self) -> str:
        """Return the complete target path used in violation messages."""
        return ".".join(filter(None, (self.module, self.symbol)))


def _call_argument(call: ast.Call, position: int, keyword_name: str) -> ast.expr | None:
    """Return a positional or explicitly named call argument."""
    if len(call.args) > position:
        return call.args[position]
    return next(
        (keyword.value for keyword in call.keywords if keyword.arg == keyword_name),
        None,
    )


def domain_dependencies(
    project_root: Path,
    modules: tuple[str, ...],
) -> dict[str, set[ImportTarget]]:
    """Return full direct domain import paths found under each module package."""
    dependencies: dict[str, set[ImportTarget]] = {module: set() for module in modules}
    module_set = set(modules)

    for owner in modules:
        for path in sorted((project_root / owner).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            import_module_names = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == "importlib"
                for alias in node.names
                if alias.name == "import_module"
            }
            importlib_names = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
                if alias.name == "importlib"
            }
            imported_import_module_names = frozenset(import_module_names)
            import_module_names.update(
                target.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(target := node.targets[0], ast.Name)
                and (
                    (
                        isinstance(node.value, ast.Name)
                        and node.value.id in imported_import_module_names
                    )
                    or (
                        isinstance(node.value, ast.Attribute)
                        and node.value.attr == "import_module"
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id in importlib_names
                    )
                )
            )
            dunder_import_names = {
                "__import__",
                *(
                    target.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(target := node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "__import__"
                ),
            }
            for node in ast.walk(tree):
                imported_targets: set[ImportTarget] = set()
                if isinstance(node, ast.Import):
                    imported_targets = {
                        ImportTarget(alias.name) for alias in node.names
                    }
                elif (
                    isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                ):
                    if "." in node.module:
                        imported_targets = {
                            ImportTarget(node.module, alias.name)
                            for alias in node.names
                        }
                    else:
                        imported_targets = {
                            ImportTarget(f"{node.module}.{alias.name}")
                            for alias in node.names
                        }
                elif isinstance(node, ast.Call):
                    is_import_module = (
                        isinstance(node.func, ast.Name)
                        and node.func.id in import_module_names
                    ) or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_module"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in importlib_names
                    )
                    is_dunder_import = (
                        isinstance(node.func, ast.Name)
                        and node.func.id in dunder_import_names
                    )
                    module_arg = _call_argument(node, 0, "name")
                    if (
                        (is_import_module or is_dunder_import)
                        and isinstance(module_arg, ast.Constant)
                        and isinstance(module_arg.value, str)
                    ):
                        module_name = module_arg.value
                        package_arg = _call_argument(node, 1, "package")
                        if (
                            is_import_module
                            and module_name.startswith(".")
                            and isinstance(package_arg, ast.Constant)
                            and isinstance(package_arg.value, str)
                        ):
                            try:
                                module_name = resolve_name(
                                    module_name,
                                    package_arg.value,
                                )
                            except ImportError:
                                continue
                        imported_targets = {ImportTarget(module_name)}
                dependencies[owner].update(
                    target
                    for target in imported_targets
                    if target.module.split(".", 1)[0] in module_set
                    and target.module.split(".", 1)[0] != owner
                )

    return dependencies


def _private_violation_paths(
    owner: str,
    target: ImportTarget,
) -> tuple[str, ...]:
    """Return a private target path, or nothing when its public contract allows it."""
    dependency = target.module.split(".", 1)[0]
    edge_symbols = EDGE_PUBLIC_SYMBOLS.get((owner, dependency))
    if edge_symbols is not None:
        allowed_symbols = edge_symbols.get(target.module)
        if allowed_symbols is None:
            return (target.module,)
        if target.symbol in allowed_symbols:
            return ()
        return (target.path,)

    target_symbols = TARGET_PUBLIC_SYMBOLS.get(target.module)
    if target_symbols is not None:
        if target.symbol in target_symbols:
            return ()
        return (target.path,)

    parts = target.module.split(".")
    if len(parts) == 2 and parts[1] in PUBLIC_BOUNDARIES:
        return ()
    return (target.module,)


def architecture_violations(
    dependencies: Mapping[str, set[ImportTarget]],
    allowed: Mapping[str, set[str]],
) -> list[str]:
    """Return deterministic forbidden-import, private-import, and cycle violations."""
    dependency_graph = {
        owner: {target.module.split(".", 1)[0] for target in targets}
        for owner, targets in dependencies.items()
    }
    violations = [
        f"{owner} imports forbidden module {dependency}"
        for owner in sorted(dependency_graph)
        for dependency in sorted(dependency_graph[owner] - allowed[owner])
    ]
    violations.extend(
        f"{owner} imports private module {violation_path}"
        for owner in sorted(dependencies)
        for target in sorted(
            dependencies[owner], key=lambda item: (item.module, item.symbol or "")
        )
        if target.module.split(".", 1)[0] in allowed[owner]
        for violation_path in _private_violation_paths(owner, target)
    )

    visiting: list[str] = []
    visited: set[str] = set()
    reported_cycles: set[tuple[str, ...]] = set()

    def visit(module: str) -> None:
        if module in visiting:
            cycle = tuple(visiting[visiting.index(module) :] + [module])
            rotations = [
                cycle[index:-1] + cycle[:index] for index in range(len(cycle) - 1)
            ]
            canonical = min(rotations)
            if canonical not in reported_cycles:
                reported_cycles.add(canonical)
                violations.append("dependency cycle: " + " -> ".join(cycle))
            return
        if module in visited:
            return
        visiting.append(module)
        for dependency in sorted(dependency_graph[module]):
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in sorted(dependencies):
        visit(module)
    return violations
