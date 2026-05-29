"""Chapter 4: classification metrics, in **pure Python** (stdlib only).

The book evaluates every classifier with scikit-learn's
``classification_report`` (precision / recall / f1-score / support, plus
accuracy and macro / weighted averages) and reasons about the confusion matrix.
This module reproduces that evaluation with **no numpy and no sklearn**, so the
toolkit's core stays dependency-free and the metric math is exactly
unit-testable against hand-computed values.

The numbers match scikit-learn's conventions:

* **precision** = TP / (TP + FP), with a divide-by-zero guard returning ``0.0``.
* **recall** = TP / (TP + FN), same guard.
* **f1** = harmonic mean of precision & recall (``0.0`` when both are zero).
* **support** = number of true instances of each label.
* **accuracy** = correct / total.
* **macro avg** = unweighted mean of the per-class metrics.
* **weighted avg** = support-weighted mean of the per-class metrics.

All functions accept any *hashable* labels (``0/1``, ``"pos"/"neg"``, ...), so
they work for the book's binary sentiment task and for multiclass problems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

Label = object  # any hashable label (int, str, ...)


def _check_lengths(y_true: Sequence, y_pred: Sequence) -> None:
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"y_true and y_pred must have the same length, got "
            f"{len(y_true)} and {len(y_pred)}."
        )


def unique_labels(*sequences: Sequence) -> List:
    """Sorted list of the distinct labels appearing across the inputs.

    Sorting is attempted directly; if the labels are not mutually orderable
    (mixed types), we fall back to sorting by their ``str`` form so the order
    is at least deterministic.
    """
    seen = set()
    for seq in sequences:
        seen.update(seq)
    try:
        return sorted(seen)
    except TypeError:  # pragma: no cover - mixed unorderable label types
        return sorted(seen, key=str)


def confusion_matrix(
    y_true: Sequence,
    y_pred: Sequence,
    labels: Optional[Sequence] = None,
) -> List[List[int]]:
    """Confusion matrix ``C`` where ``C[i][j]`` counts true label ``i`` predicted as ``j``.

    Rows are the *true* classes and columns are the *predicted* classes, in the
    order given by ``labels`` (or the sorted union of observed labels if
    ``labels`` is ``None``) — matching ``sklearn.metrics.confusion_matrix``.

    For the book's binary case with ``labels=[0, 1]`` the layout is::

        [[TN, FP],
         [FN, TP]]
    """
    _check_lengths(y_true, y_pred)
    if labels is None:
        labels = unique_labels(y_true, y_pred)
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for true, pred in zip(y_true, y_pred):
        if true in index and pred in index:
            matrix[index[true]][index[pred]] += 1
    return matrix


def accuracy(y_true: Sequence, y_pred: Sequence) -> float:
    """Fraction of predictions that exactly match the true label.

    Returns ``0.0`` for empty input (rather than dividing by zero).
    """
    _check_lengths(y_true, y_pred)
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)


@dataclass(frozen=True)
class ClassMetrics:
    """Per-class precision / recall / f1 / support."""

    label: object
    precision: float
    recall: float
    f1: float
    support: int


def _safe_div(numerator: float, denominator: float) -> float:
    """Divide, returning ``0.0`` on a zero denominator (sklearn's convention)."""
    return numerator / denominator if denominator else 0.0


def per_class_metrics(
    y_true: Sequence,
    y_pred: Sequence,
    labels: Optional[Sequence] = None,
) -> List[ClassMetrics]:
    """Compute precision / recall / f1 / support for each label.

    Derived directly from the confusion matrix: for class ``i``,
    ``TP = C[i][i]``, ``FP = sum(column i) - TP``, ``FN = sum(row i) - TP``.
    """
    _check_lengths(y_true, y_pred)
    if labels is None:
        labels = unique_labels(y_true, y_pred)
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    n = len(labels)
    results: List[ClassMetrics] = []
    for i, label in enumerate(labels):
        tp = matrix[i][i]
        fp = sum(matrix[i][c] for c in range(n)) - tp
        support = sum(matrix[i])  # row total = TP + FN = true instances
        fn = support - tp
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        results.append(
            ClassMetrics(
                label=label,
                precision=precision,
                recall=recall,
                f1=f1,
                support=support,
            )
        )
    return results


def precision_recall_f1(
    y_true: Sequence,
    y_pred: Sequence,
    average: Optional[str] = "weighted",
    labels: Optional[Sequence] = None,
) -> Tuple:
    """Precision, recall and F1 — averaged or per-class.

    Args:
        average:
            * ``"weighted"`` (default, the book's choice) — support-weighted mean
              of the per-class scores, so each class is treated proportionally.
            * ``"macro"`` — unweighted mean of the per-class scores.
            * ``None`` — no averaging; returns ``(precisions, recalls, f1s)``
              as three lists, one entry per label (in ``labels`` order).

    Returns:
        For ``"weighted"`` / ``"macro"``: a ``(precision, recall, f1)`` tuple of
        floats. For ``None``: a ``(precisions, recalls, f1s)`` tuple of lists.

    Raises:
        ValueError: if ``average`` is not one of the supported values.
    """
    metrics = per_class_metrics(y_true, y_pred, labels=labels)

    if average is None:
        precisions = [m.precision for m in metrics]
        recalls = [m.recall for m in metrics]
        f1s = [m.f1 for m in metrics]
        return precisions, recalls, f1s

    if average == "macro":
        n = len(metrics)
        if n == 0:
            return 0.0, 0.0, 0.0
        precision = sum(m.precision for m in metrics) / n
        recall = sum(m.recall for m in metrics) / n
        f1 = sum(m.f1 for m in metrics) / n
        return precision, recall, f1

    if average == "weighted":
        total = sum(m.support for m in metrics)
        if total == 0:
            return 0.0, 0.0, 0.0
        precision = sum(m.precision * m.support for m in metrics) / total
        recall = sum(m.recall * m.support for m in metrics) / total
        f1 = sum(m.f1 * m.support for m in metrics) / total
        return precision, recall, f1

    raise ValueError(
        f"average must be 'weighted', 'macro' or None, got {average!r}."
    )


@dataclass(frozen=True)
class ClassificationReport:
    """A structured classification report (the data behind the printed table).

    Attributes:
        per_class: per-label precision / recall / f1 / support.
        accuracy: overall accuracy.
        macro_avg: ``(precision, recall, f1)`` unweighted means.
        weighted_avg: ``(precision, recall, f1)`` support-weighted means.
        support: total number of samples.
    """

    per_class: List[ClassMetrics]
    accuracy: float
    macro_avg: Tuple[float, float, float]
    weighted_avg: Tuple[float, float, float]
    support: int

    def as_dict(self) -> Dict[str, object]:
        """A nested dict view (akin to sklearn's ``output_dict=True``)."""
        out: Dict[str, object] = {}
        for m in self.per_class:
            out[str(m.label)] = {
                "precision": m.precision,
                "recall": m.recall,
                "f1-score": m.f1,
                "support": m.support,
            }
        out["accuracy"] = self.accuracy
        out["macro avg"] = {
            "precision": self.macro_avg[0],
            "recall": self.macro_avg[1],
            "f1-score": self.macro_avg[2],
            "support": self.support,
        }
        out["weighted avg"] = {
            "precision": self.weighted_avg[0],
            "recall": self.weighted_avg[1],
            "f1-score": self.weighted_avg[2],
            "support": self.support,
        }
        return out


def compute_report(
    y_true: Sequence,
    y_pred: Sequence,
    labels: Optional[Sequence] = None,
    target_names: Optional[Sequence[str]] = None,
) -> ClassificationReport:
    """Compute the full classification report as structured data.

    ``target_names`` (if given) rename the labels in the per-class rows and must
    match the number of labels — mirroring sklearn's argument.
    """
    if labels is None:
        labels = unique_labels(y_true, y_pred)
    metrics = per_class_metrics(y_true, y_pred, labels=labels)

    if target_names is not None:
        if len(target_names) != len(metrics):
            raise ValueError(
                f"target_names has {len(target_names)} entries but there are "
                f"{len(metrics)} labels."
            )
        metrics = [
            ClassMetrics(name, m.precision, m.recall, m.f1, m.support)
            for name, m in zip(target_names, metrics)
        ]

    return ClassificationReport(
        per_class=metrics,
        accuracy=accuracy(y_true, y_pred),
        macro_avg=precision_recall_f1(y_true, y_pred, "macro", labels=labels),
        weighted_avg=precision_recall_f1(
            y_true, y_pred, "weighted", labels=labels
        ),
        support=len(y_true),
    )


def classification_report(
    y_true: Sequence,
    y_pred: Sequence,
    labels: Optional[Sequence] = None,
    target_names: Optional[Sequence[str]] = None,
    digits: int = 2,
) -> str:
    """A readable classification report string, mirroring sklearn's layout.

    Reproduces the book's ``evaluate_performance`` output: a table with
    precision / recall / f1-score / support per class, then ``accuracy`` and the
    ``macro avg`` / ``weighted avg`` rows.

    Example (matches the book's task-specific model report)::

                         precision    recall  f1-score   support

        Negative Review       0.76      0.88      0.81       533
        Positive Review       0.86      0.72      0.78       533

               accuracy                           0.80      1066
              macro avg       0.81      0.80      0.80      1066
           weighted avg       0.81      0.80      0.80      1066
    """
    report = compute_report(
        y_true, y_pred, labels=labels, target_names=target_names
    )

    row_names = [str(m.label) for m in report.per_class]
    last_line_names = ["accuracy", "macro avg", "weighted avg"]
    name_width = max(
        [len(n) for n in row_names] + [len(n) for n in last_line_names]
    )
    name_width = max(name_width, len("weighted avg"))

    headers = ["precision", "recall", "f1-score", "support"]
    col_width = max(len(h) for h in headers)
    col_width = max(col_width, digits + 4)  # room for "0.dd"

    def fmt_num(value: float) -> str:
        return f"{value:>{col_width}.{digits}f}"

    def fmt_int(value: int) -> str:
        return f"{value:>{col_width}d}"

    def fmt_blank() -> str:
        return " " * col_width

    lines: List[str] = []
    header = " " * name_width + "  " + "  ".join(
        f"{h:>{col_width}}" for h in headers
    )
    lines.append(header)
    lines.append("")

    for m in report.per_class:
        lines.append(
            f"{str(m.label):>{name_width}}  "
            f"{fmt_num(m.precision)}  {fmt_num(m.recall)}  "
            f"{fmt_num(m.f1)}  {fmt_int(m.support)}"
        )

    lines.append("")
    # accuracy: only the f1-score column carries a value (sklearn style).
    lines.append(
        f"{'accuracy':>{name_width}}  "
        f"{fmt_blank()}  {fmt_blank()}  "
        f"{fmt_num(report.accuracy)}  {fmt_int(report.support)}"
    )
    mp, mr, mf = report.macro_avg
    lines.append(
        f"{'macro avg':>{name_width}}  "
        f"{fmt_num(mp)}  {fmt_num(mr)}  {fmt_num(mf)}  "
        f"{fmt_int(report.support)}"
    )
    wp, wr, wf = report.weighted_avg
    lines.append(
        f"{'weighted avg':>{name_width}}  "
        f"{fmt_num(wp)}  {fmt_num(wr)}  {fmt_num(wf)}  "
        f"{fmt_int(report.support)}"
    )

    return "\n".join(lines)
