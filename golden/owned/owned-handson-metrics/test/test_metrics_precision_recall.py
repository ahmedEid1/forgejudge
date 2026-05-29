"""Regression tests for precision / recall arithmetic.

For class 1 in the asymmetric example the confusion matrix is::

    [[TN=2, FP=2],
     [FN=0, TP=6]]

so precision = TP/(TP+FP) = 6/8 = 0.75 and recall = TP/(TP+FN) = 6/6 = 1.0.
These must NOT be equal — precision and recall diverge whenever there are false
positives but no false negatives (or vice versa). The weighted average must
reflect the true 0.75 precision for class 1, not collapse to accuracy.
"""

import math

from metrics import per_class_metrics, precision_recall_f1

Y_TRUE = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
Y_PRED = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1]


def _by_label():
    return {m.label: m for m in per_class_metrics(Y_TRUE, Y_PRED, labels=[0, 1])}


def test_precision_counts_false_positives():
    # Class 1 has 2 false positives, so precision is 0.75, not 1.0.
    assert math.isclose(_by_label()[1].precision, 0.75)


def test_precision_and_recall_differ_when_matrix_is_asymmetric():
    m1 = _by_label()[1]
    assert not math.isclose(m1.precision, m1.recall)


def test_class0_precision_and_recall():
    # Class 0: TP=2, FP=0 (no zero was predicted wrongly as... wait) ->
    #   column 0 = [2, 0] so FP for class 0 = 0  -> precision = 1.0
    #   row 0    = [2, 2] so FN for class 0 = 2  -> recall = 2/4 = 0.5
    m0 = _by_label()[0]
    assert math.isclose(m0.precision, 1.0)
    assert math.isclose(m0.recall, 0.5)


def test_weighted_precision_uses_true_per_class_values():
    # weighted precision = (4*1.0 + 6*0.75) / 10 = 0.85
    precision, _recall, _f1 = precision_recall_f1(
        Y_TRUE, Y_PRED, average="weighted", labels=[0, 1]
    )
    assert math.isclose(precision, 0.85)
