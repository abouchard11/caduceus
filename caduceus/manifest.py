"""The skill shelf, as data: name + description from every SKILL.md across
the configured roots, plus the denylist of reach.

Nothing here loads a skill. The manifest exists so the loadout proposer can
see ~1,000 skills without paying their context cost, and so the install step
can find a skill's directory by name (docs/compile-design.md §3.5–3.6).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import config

MANIFEST_SCHEMA = "caduceus.manifest.v1"
DESCRIPTION_MAX = 300
DENYLIST_FILE = "DENYLIST.json"

Root = Tuple[str, Path, int]   # (label, path, max_depth of SKILL.md relative to root)

# A skill name is used as a single path component under a seat's skills/
# directory, and it comes from third-party frontmatter: it must be exactly
# one safe component (security review 2026-10-10).
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def safe_name(name: str) -> bool:
    return bool(name) and _SAFE.fullmatch(name) is not None and name not in (".", "..")


@dataclass
class Entry:
    name: str
    description: str
    root: str
    path: str                 # the SKILL.md path; the skill directory is its parent
    category: str
    user_invoked: bool
    sha256: str
    empty_description: bool


@dataclass
class Manifest:
    entries: List[Entry] = field(default_factory=list)
    shadowed: List[Tuple[str, str]] = field(default_factory=list)
    skipped_roots: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    generated: str = ""

    def by_name(self) -> Dict[str, Entry]:
        return {e.name: e for e in self.entries}

    def to_json(self) -> dict:
        return {"schema": MANIFEST_SCHEMA, "generated": self.generated,
                "counts": dict(self.counts), "skipped_roots": list(self.skipped_roots),
                "shadowed": [list(s) for s in self.shadowed],
                "entries": [asdict(e) for e in self.entries]}

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_json(), indent=1, ensure_ascii=False) + "\n")


def load(path: Path) -> Manifest:
    d = json.loads(Path(path).read_text())
    if d.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"{path}: not a {MANIFEST_SCHEMA} file")
    return Manifest(entries=[Entry(**e) for e in d.get("entries", [])],
                    shadowed=[tuple(s) for s in d.get("shadowed", [])],
                    skipped_roots=list(d.get("skipped_roots", [])),
                    counts=dict(d.get("counts", {})), generated=d.get("generated", ""))


def default_roots() -> List[Root]:
    home = Path.home()
    return [("global", home / ".claude" / "skills", 2),
            ("plugins", home / ".claude" / "plugins" / "cache", 8),
            ("hermes", config.hermes_home() / "skills", 4),
            ("repo", config.repo_root() / "skills", 2)]


def default_manifest_path() -> Path:
    return config.caduceus_home() / "skill-manifest.json"


# ---------------------------------------------------------------- frontmatter

def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> Dict[str, str]:
    """Minimal YAML-ish frontmatter: `key: value` lines between the first two
    `---` lines; `>` folds following indented lines with spaces, `|` keeps
    newlines. Anything else (lists, nested maps) is returned as its raw text."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: Dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value in (">", "|", ">-", "|-"):
                block: List[str] = []
                i += 1
                while i < len(lines) and (lines[i].startswith((" ", "\t")) or lines[i].strip() == ""):
                    if lines[i].strip() == "---":
                        break
                    block.append(lines[i].strip())
                    i += 1
                out[key] = (" " if value.startswith(">") else "\n").join(b for b in block if b)
                continue
            out[key] = _unquote(value)
        i += 1
    return out


# ---------------------------------------------------------------- scan

PRUNE_DIRS = {"node_modules", "__pycache__", ".git"}


def _category(label: str, rel: Path) -> str:
    parts = rel.parts
    if label == "plugins" and "skills" in parts:
        k = parts.index("skills")           # <marketplace>/<plugin>/<version>/skills/<name>
        if k >= 2:
            return parts[k - 2]
        if k >= 1:
            return parts[k - 1]
    return parts[0] if len(parts) > 1 else ""


def _skill_files(root: Path, max_depth: int):
    """Every SKILL.md under root within max_depth, following directory
    symlinks (a third of ~/.claude/skills are links) without looping, and
    never descending into node_modules, __pycache__, .git or dot-directories."""
    seen = set()
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        depth = len(Path(dirpath).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if d not in PRUNE_DIRS and not d.startswith("."))
        if depth >= max_depth:
            dirs[:] = []
        if "SKILL.md" in files and depth <= max_depth:
            yield Path(dirpath) / "SKILL.md"


def scan(roots: Optional[Sequence[Root]] = None, extra: Iterable[Root] = ()) -> Manifest:
    import time
    roots = list(roots if roots is not None else default_roots()) + list(extra)
    m = Manifest(generated=time.strftime("%Y-%m-%dT%H:%M:%S"))
    seen: Dict[str, Entry] = {}
    for label, root, max_depth in roots:
        root = Path(root)
        if not root.is_dir():
            m.skipped_roots.append(label)
            continue
        count = 0
        for skill_md in _skill_files(root, max_depth):
            rel = skill_md.relative_to(root)
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_frontmatter(text)
            name = (fm.get("name") or "").strip()
            if not safe_name(name):
                name = skill_md.parent.name
                if not safe_name(name):
                    m.shadowed.append((name, str(skill_md)))   # unusable as a component; recorded, not loaded
                    continue
            desc = " ".join(fm.get("description", "").split())[:DESCRIPTION_MAX]
            entry = Entry(
                name=name, description=desc, root=label, path=str(skill_md),
                category=_category(label, rel),
                user_invoked=fm.get("disable-model-invocation", "").strip().lower() in ("true", "yes"),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                empty_description=not desc,
            )
            if name in seen:
                m.shadowed.append((name, str(skill_md)))
                continue
            seen[name] = entry
            m.entries.append(entry)
            count += 1
        m.counts[label] = count
    return m


# ---------------------------------------------------------------- denylist

@dataclass
class Denylist:
    names: set = field(default_factory=set)
    patterns: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, repo_root: Path) -> "Denylist":
        path = Path(repo_root) / "seats" / DENYLIST_FILE
        if not path.exists():
            return cls()
        d = json.loads(path.read_text())
        return cls(names={n.lower() for n in d.get("names", [])},
                   patterns=[p.lower() for p in d.get("patterns", [])])

    def _forms(self, name: str) -> List[str]:
        n = name.strip().lower()
        forms = [n]
        if ":" in n:
            forms.append(n.rsplit(":", 1)[1])
        return forms

    def denies(self, name: str) -> bool:
        for f in self._forms(name):
            if f in self.names:
                return True
            if any(fnmatch.fnmatchcase(f, p) for p in self.patterns):
                return True
        return False

    def filter(self, entries: Iterable[Entry]) -> Tuple[List[Entry], List[Entry]]:
        kept, denied = [], []
        for e in entries:
            (denied if self.denies(e.name) else kept).append(e)
        return kept, denied
