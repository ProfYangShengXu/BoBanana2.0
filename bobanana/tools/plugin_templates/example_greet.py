"""Example Python drop-in plugin for .bobanana/tools/

Copy or edit this file; run /reload-tools after changes.
"""

from bobanana.tools.plugin_registry import register_tool


@register_tool(
    "plugin_greet",
    version="1.0.0",
    description="Example Python plugin — greets by name",
    permissions=["read"],
)
def plugin_greet(name: str = "BoBanana") -> str:
    return f"Hello, {name}! (from plugin_greet v1.0.0)"
