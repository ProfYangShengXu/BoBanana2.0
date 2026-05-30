"""Drop-in tool plugins: decorator registration + YAML manifests + hot load.

Plugins live under ``<data_dir>/tools/`` (typically ``.bobanana/tools/``):
  - ``*.yaml``  — declarative manifests (echo / shell handlers)
  - ``*.py``    — Python modules using ``@register_tool``
  - ``README.md`` — human + agent documentation (seeded on first run)

Core built-in tools are registered in ``registry.py`` with the same metadata model.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from ..logging_setup import get_logger
from .permissions import Permission, format_permissions, parse_permissions
from .shell_tools import ShellRunner

log = get_logger("tool_plugins")

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$")


def normalize_version(version: str) -> str:
    v = (version or "1.0.0").strip()
    if not _SEMVER_RE.match(v):
        raise ValueError(f"invalid semver: {version!r} (expected MAJOR.MINOR.PATCH)")
    return v


@dataclass
class ToolSpec:
    name: str
    description: str
    version: str = "1.0.0"
    permissions: Set[Permission] = field(default_factory=lambda: {Permission.READ})
    source: str = "plugin"       # core | plugin | yaml | python | skills | web | mcp
    origin: str = ""             # file path or module id
    handler: str = ""            # echo | shell | python | builtin


@dataclass
class PluginContext:
    workspace: Path
    shell: ShellRunner
    memory: Any = None


class PluginLoadReport:
    def __init__(self) -> None:
        self.loaded: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[str] = []

    def ok(self) -> bool:
        return not self.errors


# Per-module registration buffer while importing a plugin .py file.
_import_buffer: List[tuple[ToolSpec, Callable[..., str]]] = []


def register_tool(
    name: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    permissions: List[str] | None = None,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Decorator for drop-in Python plugins in ``.bobanana/tools/*.py``."""

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        perms = parse_permissions(permissions or ["read"])
        spec = ToolSpec(
            name=name,
            description=description or fn.__doc__ or "",
            version=normalize_version(version),
            permissions=perms,
            source="python",
            handler="python",
        )
        _import_buffer.append((spec, fn))
        return fn

    return decorator


def _yaml_param_fields(params: dict) -> dict[str, tuple[type, Any]]:
    fields: dict[str, tuple[type, Any]] = {}
    for pname, pdef in (params or {}).items():
        if not isinstance(pdef, dict):
            continue
        ptype = str(pdef.get("type", "string")).lower()
        desc = str(pdef.get("description", ""))
        default = pdef.get("default", ...)
        py_type = str if ptype in ("string", "str") else int if ptype in ("int", "integer") else str
        if default is ...:
            fields[pname] = (py_type, Field(description=desc))
        else:
            fields[pname] = (py_type, Field(default=default, description=desc))
    return fields


def _make_args_schema(name: str, params: dict) -> Type[BaseModel]:
    fields = _yaml_param_fields(params)
    if not fields:
        return create_model(f"{name}_Args")
    return create_model(f"{name}_Args", **fields)


class PluginLoader:
    """Scan ``plugin_dir`` and produce StructuredTool instances."""

    def __init__(self, plugin_dir: Path, ctx: PluginContext) -> None:
        self.plugin_dir = plugin_dir
        self.ctx = ctx
        self.report = PluginLoadReport()
        self.specs: Dict[str, ToolSpec] = {}

    def scan(self) -> List[StructuredTool]:
        if not self.plugin_dir.is_dir():
            self.report.skipped.append(f"{self.plugin_dir} (not a directory)")
            return []

        tools: List[StructuredTool] = []
        for path in sorted(self.plugin_dir.iterdir()):
            if path.name.startswith(".") or path.name == "README.md":
                continue
            try:
                if path.suffix.lower() in (".yaml", ".yml"):
                    tools.extend(self._load_yaml(path))
                elif path.suffix.lower() == ".py" and path.name != "__init__.py":
                    tools.extend(self._load_python(path))
            except Exception as exc:
                msg = f"{path.name}: {type(exc).__name__}: {exc}"
                self.report.errors.append(msg)
                log.warning("plugin load failed: %s", msg)

        return tools

    def _load_yaml(self, path: Path) -> List[StructuredTool]:
        try:
            import yaml
        except ImportError:
            raise RuntimeError("PyYAML required for YAML tool manifests (pip install pyyaml)") from None

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping")

        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("manifest missing 'name'")

        version = normalize_version(str(data.get("version", "1.0.0")))
        description = str(data.get("description", "")).strip()
        perms = parse_permissions(data.get("permissions") or ["read"])
        handler = str(data.get("handler", "echo")).strip().lower()
        params = data.get("parameters") or {}
        args_schema = _make_args_schema(name, params)

        spec = ToolSpec(
            name=name, description=description, version=version,
            permissions=perms, source="yaml", origin=str(path), handler=handler,
        )

        if handler == "echo":
            template = str(data.get("message", "OK: {name} v{version}"))

            def _echo(**kwargs) -> str:
                try:
                    fmt = dict(kwargs)
                    fmt.setdefault("name", name)
                    fmt.setdefault("version", version)
                    return template.format(**fmt)
                except Exception as exc:
                    return f"ERROR: echo template: {exc}"

            tool = StructuredTool.from_function(
                func=_echo, name=name, description=description, args_schema=args_schema,
            )
        elif handler == "shell":
            cmd_tpl = str(data.get("command", "")).strip()
            if not cmd_tpl:
                raise ValueError("shell handler requires 'command'")

            def _shell(**kwargs) -> str:
                try:
                    cmd = cmd_tpl.format(**kwargs)
                except Exception as exc:
                    return f"ERROR: command template: {exc}"
                return self.ctx.shell.run(cmd)

            if Permission.SHELL not in perms:
                perms.add(Permission.SHELL)
                spec.permissions = perms

            tool = StructuredTool.from_function(
                func=_shell, name=name, description=description, args_schema=args_schema,
            )
        else:
            raise ValueError(f"unsupported handler: {handler!r} (use echo or shell)")

        self._register_spec(spec, tool)
        self.report.loaded.append(f"{name}@{version} (yaml:{path.name})")
        return [tool]

    def _load_python(self, path: Path) -> List[StructuredTool]:
        global _import_buffer
        _import_buffer = []
        mod_name = f"bobanana_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        out: List[StructuredTool] = []
        for pspec, fn in _import_buffer:
            pspec.origin = str(path)
            pspec.source = "python"

            def _make_bound(f: Callable[..., str], ctx: PluginContext) -> Callable[..., str]:
                def _bound(**kwargs) -> str:
                    # Inject ctx only if the function accepts it.
                    import inspect
                    sig = inspect.signature(f)
                    if "ctx" in sig.parameters:
                        kwargs["ctx"] = ctx
                    return f(**kwargs)

                return _bound

            bound = _make_bound(fn, self.ctx)
            tool = StructuredTool.from_function(
                func=bound, name=pspec.name, description=pspec.description,
            )
            self._register_spec(pspec, tool)
            self.report.loaded.append(f"{pspec.name}@{pspec.version} (py:{path.name})")
            out.append(tool)
        _import_buffer = []
        return out

    def _register_spec(self, spec: ToolSpec, tool: StructuredTool) -> None:
        if spec.name in self.specs:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self.specs[spec.name] = spec
        setattr(tool, "_bobanana_spec", spec)


def wrap_with_permissions(tool: StructuredTool, spec: ToolSpec, policy) -> StructuredTool:
    """Return a StructuredTool whose func checks permissions before running."""
    original = tool.func

    def guarded(*args, **kwargs):
        if not policy.allows(spec.permissions):
            return policy.deny_message(spec.name, spec.permissions)
        return original(*args, **kwargs)

    return StructuredTool.from_function(
        func=guarded,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def spec_for_core(name: str, description: str, permissions: Set[Permission],
                  version: str = "1.0.0", source: str = "core") -> ToolSpec:
    return ToolSpec(
        name=name, description=description, version=normalize_version(version),
        permissions=permissions, source=source, origin="bobanana/tools/registry.py",
        handler="builtin",
    )
