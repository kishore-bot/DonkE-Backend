import ast
from graphlib import TopologicalSorter
from importlib.util import resolve_name
from pathlib import Path


def test_application_imports_are_acyclic() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = {
        ".".join(path.relative_to(root).with_suffix("").parts).removesuffix(
            ".__init__"
        ): path
        for path in (root / "app").rglob("*.py")
    }
    graph = TopologicalSorter()
    for name, path in modules.items():
        package = name if path.stem == "__init__" else name.rpartition(".")[0]
        # Python imports the enclosing packages before loading a submodule.
        imports: set[str] = {name.rpartition(".")[0]}
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                source = node.module or ""
                if node.level:
                    source = resolve_name("." * node.level + source, package)
                if source != name:
                    imports.add(source)
                imports.update(f"{source}.{alias.name}" for alias in node.names)
        local_imports = imports.intersection(modules)
        if name.startswith("app.core.") and name != "app.core.schema":
            upstream = {
                target
                for target in local_imports
                if target == "app.core.schema"
                or target == "app.modules"
                or target.startswith("app.modules.")
            }
            assert not upstream, f"{name} depends on feature registration {upstream}"
        graph.add(name, *sorted(local_imports))
    tuple(graph.static_order())
