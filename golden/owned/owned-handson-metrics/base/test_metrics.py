"""Tests for the pure-Python classification metrics (book Ch.4).

These cover the confusion matrix, accuracy, label discovery, and per-class
support — the structural pieces that don't depend on the precision/recall
arithmetic.
"""

from metrics import (
    accuracy,
    confusion_matrix,
    per_class_metrics,
    unique_labels,
)

# Asymmetric binary example used across the suite.
#   true 0: pred [0,0,1,1]  -> row [2, 2]
#   true 1: pred [1,1,1,1,1,1] -> row [0, 6]
Y_TRUE = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
Y_PRED = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1]


def test_unique_labels_sorted_union():
    assert unique_labels([0, 0, 1], [1, 1, 0]) == [0, 1]


def test_unique_labels_string_labels():
    assert unique_labels(["pos", "neg"], ["neg"]) == ["neg", "pos"]


def test_confusion_matrix_layout():
    # Rows are true classes, columns are predicted classes: [[TN, FP], [FN, TP]].
    assert confusion_matrix(Y_TRUE, Y_PRED, labels=[0, 1]) == [[2, 2], [0, 6]]


def test_confusion_matrix_diagonal_is_correct_predictions():
    cm = confusion_matrix(Y_TRUE, Y_PRED, labels=[0, 1])
    diag = sum(cm[i][i] for i in range(len(cm)))
    assert diag == sum(1 for t, p in zip(Y_TRUE, Y_PRED) if t == p)


def test_accuracy_matches_manual_count():
    assert accuracy(Y_TRUE, Y_PRED) == 0.8


def test_accuracy_empty_is_zero():
    assert accuracy([], []) == 0.0


def test_per_class_support_is_true_instance_count():
    metrics = {m.label: m for m in per_class_metrics(Y_TRUE, Y_PRED, labels=[0, 1])}
    # support = number of TRUE instances of each class (row totals).
    assert metrics[0].support == 4
    assert metrics[1].support == 6


def test_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        confusion_matrix([0, 1], [0])
