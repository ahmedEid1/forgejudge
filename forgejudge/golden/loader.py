"""Load and validate the canonical golden-set dataset (``golden/dataset.jsonl``).

One JSON object per line, each a :class:`forgejudge.types.Task`. The JSONL file
committed to Git is the canonical source of truth (the Neon copy is derived).
"""

from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from forgejudge.types import Task


def load_tasks(path: str | Path) -> list[Task]:
    """Parse ``path`` into a list of :class:`Task`.

    Raises ``ValueError`` (naming the offending 1-based line number) on a
    malformed or schema-invalid line, and on any duplicate ``instance_id``.
    """
    path = Path(path)
    tasks: list[Task] = []
    # Split ONLY on the literal record separator the writer used ('\n'); never on
    # str.splitlines()'s full Unicode line-boundary set (U+2028/U+2029, \x0b,
    # \x0c, ...), which are legal *inside* a JSON string and are emitted raw by
    # model_dump_json — so splitlines() would tear a single record in two
    # (Finding #20). Strip a trailing '\r' per line for CRLF tolerance.
    for lineno, raw in enumerate(path.read_text().split("\n"), start=1):
        raw = raw.rstrip("\r")
        if not raw.strip():
            continue
        try:
            tasks.append(Task.model_validate_json(raw))
        except ValidationError as exc:
            raise ValueError(f"{path}: line {lineno}: invalid task: {exc}") from exc
    validate_dataset(tasks)
    return tasks


def validate_dataset(tasks: list[Task]) -> None:
    """Raise ``ValueError`` if any ``instance_id`` is duplicated."""
    counts = Counter(t.instance_id for t in tasks)
    dupes = sorted(iid for iid, n in counts.items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate instance_id(s): {', '.join(dupes)}")
