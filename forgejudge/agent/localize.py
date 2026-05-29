"""Fault localization: rank a repo's Python files most-likely-buggy first.

The agent edits *source*, so before it can propose a patch it must decide *which*
file(s) to touch. ``localize`` does this with BM25 lexical retrieval (the ``bm25s``
library — pure-Python, no database, no network, $0): it tokenizes every non-test
Python file (contents + path) into a corpus, builds a query from the task's
``problem_statement`` plus the basenames/symbols referenced by its failing tests,
and returns the top-k highest-scoring file paths.

Hybrid extension point
-----------------------
Lexical BM25 is the cheap first stage. A later phase can add a dense pgvector
recall stage and a cross-encoder rerank *behind this same signature* — embed the
files into pgvector, union the dense top-N with the BM25 top-N here, rerank the
union, then truncate to ``top_k``. The public contract (``localize(task, repo_dir,
*, top_k) -> list[str]``) does not change, so callers never learn that the
retrieval became hybrid. That work is deliberately out of scope here: this stays
BM25-only with no DB.
"""

import re
from pathlib import Path

import bm25s

from forgejudge.types import Task

# Keep identifier-ish tokens (``calculate_discount``, ``v2``) rather than the
# default which drops single chars; we additionally split snake/camel below.
_TOKEN_PATTERN = r"(?u)\b\w+\b"

# A node id looks like ``path/to/test_foo.py::TestX::test_bar`` — pull out the
# file basename and the symbol names so they can seed the query.
_NODE_SPLIT = re.compile(r"[/:]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _is_test_file(rel: Path) -> bool:
    """True for files the agent must never edit (the test suite)."""
    name = rel.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    # Anything under a ``test`` / ``tests`` directory is a test asset too.
    return any(part in {"test", "tests"} for part in rel.parts[:-1])


def _expand_identifiers(text: str) -> list[str]:
    """Split identifiers so ``calculate_discount`` / ``parseUrl`` also match as parts."""
    parts: list[str] = []
    for raw in re.findall(_TOKEN_PATTERN, text):
        parts.append(raw)
        # snake_case -> components; camelCase -> components.
        snake = raw.split("_")
        if len(snake) > 1:
            parts.extend(p for p in snake if p)
        camel = _CAMEL.split(raw)
        if len(camel) > 1:
            parts.extend(p for p in camel if p)
    return parts


def _collect_candidates(repo_dir: Path) -> list[Path]:
    """Repo-relative paths of every non-test ``.py`` file, sorted for determinism."""
    candidates: list[Path] = []
    for path in sorted(repo_dir.rglob("*.py")):
        rel = path.relative_to(repo_dir)
        if _is_test_file(rel):
            continue
        candidates.append(rel)
    return candidates


def _build_query(task: Task) -> str:
    """Query text: the problem statement plus symbols/basenames from failing tests."""
    parts = [task.problem_statement]
    for node_id in task.fail_to_pass:
        for piece in _NODE_SPLIT.split(node_id):
            if not piece:
                continue
            # Drop the ``.py`` so ``test_semver.py`` contributes ``test``/``semver``.
            parts.append(piece.removesuffix(".py"))
    return " ".join(parts)


def localize(task: Task, repo_dir: str | Path, *, top_k: int = 5) -> list[str]:
    """Rank ``repo_dir``'s Python source files most-likely-buggy first.

    Returns up to ``top_k`` repo-relative ``.py`` paths (POSIX separators), ordered
    by descending BM25 relevance to the task. Test files are excluded from the
    candidate set — the agent edits source, not the suite — and an empty repo (or
    one with no scoreable source) yields ``[]``.
    """
    repo = Path(repo_dir)
    if not repo.is_dir():
        return []

    candidates = _collect_candidates(repo)
    if not candidates:
        return []

    # Each document = file contents + its path, so a filename like ``discount.py``
    # that echoes a symbol in the problem statement contributes to the score.
    documents: list[str] = []
    for rel in candidates:
        try:
            contents = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            contents = ""
        path_tokens = " ".join(_expand_identifiers(rel.as_posix()))
        documents.append(f"{contents}\n{path_tokens}")

    corpus_tokens = bm25s.tokenize(
        [" ".join(_expand_identifiers(doc)) for doc in documents],
        stopwords="en",
        token_pattern=_TOKEN_PATTERN,
        show_progress=False,
    )
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)

    query_tokens = bm25s.tokenize(
        " ".join(_expand_identifiers(_build_query(task))),
        stopwords="en",
        token_pattern=_TOKEN_PATTERN,
        show_progress=False,
    )

    rel_paths = [rel.as_posix() for rel in candidates]
    k = min(top_k, len(rel_paths))
    results, scores = retriever.retrieve(
        query_tokens, corpus=rel_paths, k=k, show_progress=False
    )

    # ``retrieve`` returns a batch of one query; keep only positively-scored hits
    # so we never surface a file that shares no terms with the task.
    ranked = [
        path for path, score in zip(results[0], scores[0], strict=True) if score > 0
    ]
    return ranked
