"""Web reach: search, fetch, and import external code.

- ``web_search``  : keyless DuckDuckGo search.
- ``fetch_url``   : fetch a page/raw file and return readable text (scrape code).
- ``clone_repo``  : git-clone an external repo into the workspace and index it
                    into structured memory (import external libraries).

All are best-effort: on missing deps / no network they return an ERROR string the
agent can reason about, rather than raising.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..logging_setup import get_logger
from ..memory import MemoryManager
from ..version import __version__

log = get_logger("web")

_CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c",
             ".cpp", ".h", ".hpp", ".rb", ".php", ".cs", ".sh", ".md", ".json",
             ".toml", ".yaml", ".yml", ".txt"}


class WebTools:
    def __init__(self, workspace: Path, memory: MemoryManager, timeout: int = 30) -> None:
        self.workspace = workspace.resolve()
        self.memory = memory
        self.timeout = timeout

    # ----- search -----
    def web_search(self, query: str, max_results: int = 5) -> str:
        query = (query or "").strip()
        if not query:
            return "ERROR: empty query"
        try:
            from ddgs import DDGS
        except ImportError:
            return "ERROR: 'ddgs' package not installed"
        log.info("web_search: %s", query)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
        except Exception as exc:
            log.error("web_search failed: %s", exc)
            return f"ERROR: search failed: {type(exc).__name__}: {exc}"
        if not results:
            return "(no results)"
        lines = []
        for i, r in enumerate(results, start=1):
            title = r.get("title", "")
            href = r.get("href") or r.get("url", "")
            body = (r.get("body", "") or "")[:200]
            lines.append(f"{i}. {title}\n   {href}\n   {body}")
        return "\n".join(lines)

    # ----- fetch -----
    def fetch_url(self, url: str, max_chars: int = 12000) -> str:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return "ERROR: url must start with http:// or https://"
        log.info("fetch_url: %s", url)
        try:
            import httpx
        except ImportError:
            return "ERROR: 'httpx' package not installed"
        try:
            resp = httpx.get(url, timeout=self.timeout, follow_redirects=True,
                             headers={"User-Agent": f"BoBanana/{__version__} (+agent)"})
            resp.raise_for_status()
        except Exception as exc:
            log.error("fetch_url failed: %s", exc)
            return f"ERROR: fetch failed: {type(exc).__name__}: {exc}"

        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "html" in ctype:
            text = self._html_to_text(text)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
        return text

    @staticmethod
    def _html_to_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return "\n".join(line for line in soup.get_text("\n").splitlines() if line.strip())

    # ----- clone + index -----
    def clone_repo(self, git_url: str, dest: str = "", max_index: int = 200) -> str:
        git_url = (git_url or "").strip()
        if not git_url:
            return "ERROR: empty git url"
        name = dest.strip() or git_url.rstrip("/").split("/")[-1].removesuffix(".git")
        target = (self.workspace / "external" / name).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError:
            return "ERROR: destination escapes workspace"
        log.info("clone_repo: %s -> %s", git_url, target)
        try:
            if target.exists():
                proc = subprocess.run(["git", "-C", str(target), "pull", "--ff-only"],
                                      capture_output=True, text=True, timeout=180)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                proc = subprocess.run(["git", "clone", "--depth", "1", git_url, str(target)],
                                      capture_output=True, text=True, timeout=180)
        except FileNotFoundError:
            return "ERROR: git is not installed or not on PATH"
        except subprocess.TimeoutExpired:
            return "ERROR: git operation timed out"
        if proc.returncode != 0:
            return f"ERROR: git failed (exit {proc.returncode}):\n{proc.stderr.strip()}"

        indexed = self._index_repo(target, max_index)
        rel = target.relative_to(self.workspace)
        return (f"OK: cloned into {rel}. Indexed {indexed} file(s) into structured memory. "
                f"Use list_dir/read_file under '{rel}' to read the code.")

    def _index_repo(self, root: Path, max_index: int) -> int:
        count = 0
        for path in sorted(root.rglob("*")):
            if count >= max_index:
                break
            if ".git" in path.parts or not path.is_file():
                continue
            if path.suffix.lower() not in _CODE_EXT:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(path.relative_to(self.workspace))
            summary = (text.strip().splitlines() or ["(empty)"])[0][:120]
            self.memory.record_file(rel, summary=f"[external] {summary}", lines=text.count("\n") + 1)
            count += 1
        self.memory.record_fact(f"repo:{root.name}", f"imported from clone, {count} files indexed",
                                category="repo")
        return count
