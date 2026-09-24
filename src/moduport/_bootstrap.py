"""Load bundled frozen mechanics and private dependencies package-relatively."""

from __future__ import annotations

from importlib import import_module, util
from pathlib import Path
import sys
from types import ModuleType


_STATE: dict[str, object] | None = None


def _paths() -> dict[str, Path]:
    package_root = Path(__file__).resolve().parent
    paths = {
        "package_root": package_root,
        "frozen": package_root / "_frozen",
        "vendor": package_root / "_vendor",
        "rv30": package_root / "_vendor" / "rv30",
        "mscsolver": package_root / "_vendor" / "mscsolver",
    }
    missing = [str(path) for path in paths.values() if not path.is_dir()]
    if missing:
        raise ImportError("incomplete ModuPort installation: " + ", ".join(missing))
    return paths


def _prepend(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _is_local(module: ModuleType, directory: Path) -> bool:
    try:
        Path(module.__file__).resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _require_local(name: str, directory: Path) -> ModuleType:
    module = import_module(name)
    if not _is_local(module, directory):
        raise ImportError(f"{name} resolved outside the installed ModuPort package: {module.__file__}")
    return module


def _load_frozen(frozen: Path) -> ModuleType:
    name = "_moduport_frozen"
    existing = sys.modules.get(name)
    if existing is not None:
        if not _is_local(existing, frozen):
            raise ImportError(f"{name} resolved outside the installed ModuPort package")
        return existing
    initializer = frozen / "__init__.py"
    spec = util.spec_from_file_location(name, initializer, submodule_search_locations=[str(frozen)])
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load frozen ModuPort package from {initializer}")
    module = util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def install() -> dict[str, object]:
    global _STATE
    if _STATE is not None:
        return _STATE

    paths = _paths()
    _prepend(paths["rv30"])
    _prepend(paths["vendor"])
    mscsolver = _require_local("mscsolver", paths["mscsolver"])
    connection_geometry = _require_local("a20_rv30_connection_geometry", paths["rv30"])
    geometry = _require_local("a20_rv30_geometry_kernel", paths["rv30"])
    adapter = _require_local("a20_rv30_moduport_adapter", paths["rv30"])

    legacy_vendor_path = str(adapter.MODUPORT_ROOT)
    if legacy_vendor_path != str(paths["vendor"]):
        sys.path[:] = [entry for entry in sys.path if entry != legacy_vendor_path]
    adapter.PROJECT_ROOT = paths["package_root"]
    adapter.OUTPUT_ROOT = paths["package_root"]
    adapter.MODUPORT_ROOT = paths["vendor"]

    frozen = _load_frozen(paths["frozen"])
    runtime = import_module("_moduport_frozen.runtime")

    def portable_validation_root() -> Path:
        return paths["rv30"]

    def portable_imports():
        return paths["rv30"], runtime._AdapterCompatibilityProxy(adapter), geometry

    runtime.validation_root = portable_validation_root
    runtime.imports = portable_imports
    _STATE = {
        "paths": paths,
        "frozen": frozen,
        "mscsolver": mscsolver,
        "rv30_adapter": adapter,
        "rv30_geometry": geometry,
        "rv30_connection_geometry": connection_geometry,
    }
    return _STATE


__all__ = ["install"]
