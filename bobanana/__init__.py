"""BoBanana 2.0 — a terminal coding agent built on LangChain + LangGraph.

Variant-ReAct planning/execution with a dedicated reviewer agent, an intent layer
that sizes tasks and scales budgets, layered memory (working + structured), and a
forge-style pure-terminal interface.
"""

from .version import RELEASE_DATE, RELEASE_TAG, __version__, version_line, version_short

__all__ = ["__version__", "RELEASE_TAG", "RELEASE_DATE", "version_line", "version_short"]
