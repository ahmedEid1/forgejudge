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
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
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
