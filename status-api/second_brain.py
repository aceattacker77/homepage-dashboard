"""Second-brain card behind the /second-brain endpoint.

Read-only against the vault: it reads Markdown files and runs `git log` /
`git ls-files`, never writes or commits. One note is picked per day from a
hash of the date, so the pick is stable all day with no stored state.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# User-approved pool. inbox/ captures are mostly bare URLs; templates and the
# vault's own README/AGENTS are structure, not notes.
POOL_PATTERNS = (
    "notes/**/*.md",
    "decisions/**/*.md",
    "reviews/**/*.md",
    "identity/**/*.md",
    "open-questions.md",
    "projects/*/STATUS.md",
)
COUNT_EXCLUDE_PREFIXES = ("templates/", ".obsidian/", ".trash/")
EXCERPT_CHARS = 140

FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.S)
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
LINE_PREFIX = re.compile(r"^(?:>\s*|[-*+]\s+(?:\[.\]\s+)?|\d+\.\s+)+")


def note_pool(vault):
    vault = Path(vault)
    found = set()
    for pattern in POOL_PATTERNS:
        for path in vault.glob(pattern):
            if path.is_file() and not path.name.endswith(".proposed.md"):
                found.add(path.relative_to(vault).as_posix())
    return sorted(found)


def pick_note(pool, day):
    if not pool:
        return None
    digest = hashlib.sha256(day.isoformat().encode("ascii")).hexdigest()
    return pool[int(digest, 16) % len(pool)]


def parse_note(text, fallback_title):
    body = FRONT_MATTER.sub("", text.replace("\r\n", "\n"), count=1)
    title = None
    lines = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if title is None and line.startswith("# "):
                title = line[2:].strip()
            continue
        lines.append(LINE_PREFIX.sub("", line))
    excerpt = " ".join(lines)
    excerpt = WIKI_LINK.sub(lambda m: m.group(2) or m.group(1), excerpt)
    excerpt = MD_LINK.sub(r"\1", excerpt)
    excerpt = re.sub(r"\*\*|__|`", "", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[: EXCERPT_CHARS - 1].rstrip() + "…"
    return title or fallback_title, excerpt


def obsidian_uri(vault_name, rel_path=None):
    uri = "obsidian://open?vault=" + quote(vault_name, safe="")
    if rel_path:
        stem = rel_path[:-3] if rel_path.endswith(".md") else rel_path
        uri += "&file=" + quote(stem, safe="")
    return uri


def week_start_local(now):
    monday = now.date() - timedelta(days=now.weekday())
    return datetime.combine(monday, datetime.min.time(), tzinfo=now.tzinfo)


def _git_lines(vault, *args):
    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    out = subprocess.run(
        [git, "-c", "core.quotepath=off", *args],
        cwd=vault, capture_output=True, text=True, encoding="utf-8",
        timeout=10, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _created(path):
    st = path.stat()
    return min(st.st_ctime, st.st_mtime)  # st_ctime is creation time on Windows


def added_since(vault, since):
    """(sorted rel paths added since `since` that still exist, "git"|"mtime")."""
    vault = Path(vault)
    paths = set()
    try:
        paths.update(_git_lines(vault, "log", f"--since={since.isoformat()}",
                                "--diff-filter=A", "--name-only", "--format=", "--", "*.md"))
        candidates = _git_lines(vault, "ls-files", "--others", "--exclude-standard", "--", "*.md")
        source = "git"
    except (OSError, subprocess.SubprocessError):
        candidates = [p.relative_to(vault).as_posix() for p in vault.rglob("*.md")]
        source = "mtime"
    cutoff = since.timestamp()
    for rel in candidates:
        try:
            if _created(vault / rel) >= cutoff:
                paths.add(rel)
        except OSError:
            continue
    kept = sorted(p for p in paths
                  if (vault / p).is_file() and not p.startswith(COUNT_EXCLUDE_PREFIXES))
    return kept, source


def build_second_brain(vault, vault_name, now):
    vault = Path(vault)
    if not vault.is_dir():
        raise FileNotFoundError(f"vault not found: {vault}")

    pool = note_pool(vault)
    rel = pick_note(pool, now.date())
    vault_uri = obsidian_uri(vault_name)
    if rel:
        text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        title, excerpt = parse_note(text, Path(rel).stem)
        folder = Path(rel).parent.as_posix() if "/" in rel else "vault root"
        note_uri = obsidian_uri(vault_name, rel)
    else:
        title, excerpt, folder, note_uri = "No notes yet", "", "", vault_uri

    added, source = added_since(vault, week_start_local(now))
    by_folder = Counter(p.split("/", 1)[0] if "/" in p else "root" for p in added)
    breakdown = " · ".join(f"{n} {name}" for name, n in sorted(by_folder.items()))
    added_label = f"{len(added)} · {breakdown}" if added else "0"

    return {
        "note_title": title,
        "note_path": rel or "",
        "note_folder": folder,
        "note_excerpt": excerpt,
        "note_uri": note_uri,
        "added_this_week": len(added),
        "added_breakdown": breakdown,
        "added_label": added_label,
        "added_source": source,
        "pool_size": len(pool),
        "vault_uri": vault_uri,
        "items": [
            {"name": title, "label": folder, "href": note_uri},
            {"name": excerpt or "—", "label": "", "href": note_uri},
            {"name": "Added this week", "label": added_label, "href": vault_uri},
        ],
    }
