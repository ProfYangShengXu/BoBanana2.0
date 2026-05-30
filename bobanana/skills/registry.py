"""Discover, parse and load external skills (SKILL.md based).

A "skill" is any directory containing a ``SKILL.md`` whose YAML front matter has
at least a ``name``/``description``. This lets BoBanana adapt skills authored for
Cursor / Claude / Agent-Reach without code changes — the agent reads a skill's
instructions via the ``use_skill`` tool and follows them (often by shelling out
to the skill's CLI).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..logging_setup import get_logger

log = get_logger("skills")


@dataclass
class Skill:
    name: str
    description: str
    path: Path           # the SKILL.md file
    root: Path           # the skill directory
    source: str = "local"

    @property
    def root_str(self) -> str:
        return str(self.root)


def _parse_front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    try:
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


class SkillRegistry:
    def __init__(self, search_dirs: List[Path], external_dir: Path) -> None:
        self.search_dirs = [Path(d) for d in search_dirs]
        self.external_dir = Path(external_dir)
        self.external_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, Skill] = {}
        self.discover()

    def discover(self) -> int:
        """(Re)scan all search dirs for SKILL.md files. Returns count found."""
        self._skills.clear()
        roots = list(self.search_dirs) + [self.external_dir]
        for base in roots:
            if not base.exists():
                continue
            for skill_md in base.rglob("SKILL.md"):
                self._register_file(skill_md, source=str(base))
        log.info("discovered %d skill(s)", len(self._skills))
        return len(self._skills)

    def _register_file(self, skill_md: Path, source: str) -> Optional[Skill]:
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("cannot read %s: %s", skill_md, exc)
            return None
        meta = _parse_front_matter(text)
        name = str(meta.get("name") or skill_md.parent.name).strip()
        desc = str(meta.get("description") or "").strip().replace("\n", " ")
        skill = Skill(name=name, description=desc[:300], path=skill_md,
                      root=skill_md.parent, source=source)
        # First occurrence wins; later dirs don't shadow earlier explicit ones.
        self._skills.setdefault(name, skill)
        return skill

    def list(self) -> List[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name.lower())

    def get(self, name: str) -> Optional[Skill]:
        if name in self._skills:
            return self._skills[name]
        low = name.lower()
        for n, s in self._skills.items():
            if n.lower() == low:
                return s
        return None

    def read(self, name: str) -> str:
        skill = self.get(name)
        if not skill:
            available = ", ".join(s.name for s in self.list()) or "(none)"
            return f"ERROR: skill '{name}' not found. Available: {available}"
        text = skill.path.read_text(encoding="utf-8", errors="replace")
        header = f"# Skill: {skill.name}\n# Location: {skill.root}\n\n"
        return header + text

    def clone_repo(self, git_url: str, name: Optional[str] = None, timeout: int = 180) -> str:
        """Clone an external skill repo into the external dir, then re-discover."""
        if not git_url.strip():
            return "ERROR: empty git url"
        target_name = name or git_url.rstrip("/").split("/")[-1].removesuffix(".git")
        dest = self.external_dir / target_name
        try:
            if dest.exists():
                log.info("updating existing skill repo at %s", dest)
                proc = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                                      capture_output=True, text=True, timeout=timeout)
            else:
                log.info("cloning %s -> %s", git_url, dest)
                proc = subprocess.run(["git", "clone", "--depth", "1", git_url, str(dest)],
                                      capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return "ERROR: git is not installed or not on PATH"
        except subprocess.TimeoutExpired:
            return f"ERROR: git operation timed out after {timeout}s"
        if proc.returncode != 0:
            return f"ERROR: git failed (exit {proc.returncode}):\n{proc.stderr.strip()}"

        # Count SKILL.md files physically present in the repo, then re-discover.
        repo_md = list(dest.rglob("SKILL.md"))
        repo_names = []
        for md in repo_md:
            meta = _parse_front_matter(md.read_text(encoding="utf-8", errors="replace"))
            repo_names.append(str(meta.get("name") or md.parent.name).strip())
        count = self.discover()
        active_from_repo = [s.name for s in self.list() if str(dest) in str(s.root)]
        shadowed = [n for n in repo_names if n not in active_from_repo]

        if not repo_md:
            detail = "no SKILL.md found in repo (it may expose a CLI/MCP instead — use run_shell)"
        else:
            detail = f"found {len(repo_md)} SKILL.md: {', '.join(repo_names)}"
            if shadowed:
                detail += f" (already registered under another path, kept existing: {', '.join(shadowed)})"
        return f"OK: repo at {dest}. {detail}. Total skills now: {count}."
