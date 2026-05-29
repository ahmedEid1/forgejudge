"""Mutation hardening: prove a golden task's tests would catch a wrong fix.

We generate single-point mutants of the gold-fixed source (the files in
``fix/``), splice each into an otherwise-correct materialized tree, and run the
task's FAIL_TO_PASS + PASS_TO_PASS suite. A mutant is *killed* if any test
fails. A high kill rate means the tests genuinely constrain behaviour; surviving
mutants reveal weak tests (the documented ~31% weak-test failure mode).
"""

import ast
import copy
import difflib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    init_base_repo,
    run_nodeids,
)
from forgejudge.types import Task

# Single-swap mutation tables.
_CMP = {ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.LtE: ast.GtE, ast.GtE: ast.LtE,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv,
        ast.FloorDiv: ast.Mult, ast.Div: ast.Mult, ast.Mod: ast.Mult}
_BOOL = {ast.And: ast.Or, ast.Or: ast.And}


class _Counter(ast.NodeVisitor):
    """Count mutable nodes (optionally restricted to ``lines``) in traversal order."""

    def __init__(self, lines: set[int] | None = None) -> None:
        self.n = 0
        self.lines = lines

    def _in_scope(self, node: ast.AST) -> bool:
        return self.lines is None or getattr(node, "lineno", None) in self.lines

    def visit_Compare(self, node: ast.Compare) -> None:
        if self._in_scope(node) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
            self.n += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if self._in_scope(node) and type(node.op) in _BIN:
            self.n += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if self._in_scope(node) and type(node.op) in _BOOL:
            self.n += 1
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if self._in_scope(node) and isinstance(node.value, (bool, int)):
            self.n += 1
        self.generic_visit(node)


class _Mutator(ast.NodeTransformer):
    """Apply exactly the ``target``-th mutation (same order/scope as :class:`_Counter`)."""

    def __init__(self, target: int, lines: set[int] | None = None) -> None:
        self.i = -1
        self.target = target
        self.lines = lines
        self.applied = False

    def _in_scope(self, node: ast.AST) -> bool:
        return self.lines is None or getattr(node, "lineno", None) in self.lines

    def _hit(self) -> bool:
        self.i += 1
        return self.i == self.target

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if self._in_scope(node) and len(node.ops) == 1 and type(node.ops[0]) in _CMP and self._hit():
            node.ops = [_CMP[type(node.ops[0])]()]
            self.applied = True
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if self._in_scope(node) and type(node.op) in _BIN and self._hit():
            node.op = _BIN[type(node.op)]()
            self.applied = True
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if self._in_scope(node) and type(node.op) in _BOOL and self._hit():
            node.op = _BOOL[type(node.op)]()
            self.applied = True
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        self.generic_visit(node)
        if not self._in_scope(node):
            return node
        # bool is a subclass of int, so classify first, then count exactly once.
        if isinstance(node.value, bool):
            new = ast.Constant(value=not node.value)
        elif isinstance(node.value, int):
            new = ast.Constant(value=node.value + 1)
        else:
            return node
        if self._hit():
            self.applied = True
            return ast.copy_location(new, node)
        return node


def generate_mutants(source: str, lines: set[int] | None = None) -> list[tuple[str, str]]:
    """Return ``[(mutant_id, mutated_source), ...]`` — one single-point mutant each.

    If ``lines`` is given, only nodes on those (1-based) source lines are mutated —
    used to focus mutation on the gold patch's changed region (SWE-ABS style).
    """
    counter = _Counter(lines)
    counter.visit(ast.parse(source))
    mutants: list[tuple[str, str]] = []
    for i in range(counter.n):
        m = _Mutator(i, lines)
        mutated = m.visit(copy.deepcopy(ast.parse(source)))
        if not m.applied:
            continue
        ast.fix_missing_locations(mutated)
        try:
            text = ast.unparse(mutated)
        except Exception:
            continue
        if text != source.rstrip("\n") and text != source:
            mutants.append((f"mut{i}", text))
    return mutants


@dataclass
class HardenResult:
    mutants_total: int
    mutants_killed: int
    survivors: list[str] = field(default_factory=list)
    threshold: float = 0.5

    @property
    def mutation_score(self) -> float:
        return 0.0 if self.mutants_total == 0 else self.mutants_killed / self.mutants_total

    @property
    def status(self) -> str:
        """``hardened`` | ``inconclusive`` | ``weak``.

        ``inconclusive`` means the AST mutator produced no applicable mutants
        (e.g. pure string/regex code with no arithmetic/comparison/boolean
        nodes). Such a task is NOT weak: intrinsic verifiability already proves
        its FAIL_TO_PASS test executes the patched region (it could not
        distinguish buggy from fixed otherwise) — mutation is simply not
        informative for that code shape.
        """
        if self.mutants_total == 0:
            return "inconclusive"
        return "hardened" if self.mutation_score >= self.threshold else "weak"

    @property
    def passed(self) -> bool:
        return self.status != "weak"


def changed_line_numbers(base_text: str, fix_text: str) -> set[int]:
    """1-based line numbers in ``fix_text`` that differ from ``base_text``.

    These are the lines the gold patch introduced/modified — the region a wrong
    fix would occupy, and therefore where mutation is most meaningful.
    """
    base_lines = base_text.splitlines()
    fix_lines = fix_text.splitlines()
    changed: set[int] = set()
    sm = difflib.SequenceMatcher(a=base_lines, b=fix_lines, autojunk=False)
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            changed.update(range(j1 + 1, j2 + 1))  # 1-based
    return changed


def harden_check(task: Task, task_dir: str | Path, *, threshold: float = 0.5) -> HardenResult:
    """Mutate the gold patch's changed region and check the task's tests kill them.

    Mutation is restricted to the lines the fix changed (vs the buggy base), so a
    large surrounding module does not dilute the score — what matters is whether
    the tests would catch a *wrong fix at the patch site*.
    """
    task_dir = Path(task_dir)
    fix_dir = task_dir / "fix"
    base_dir = task_dir / "base"
    changed = sorted(p for p in fix_dir.rglob("*.py"))
    nodeids = list(task.fail_to_pass) + list(task.pass_to_pass)

    total = 0
    killed = 0
    survivors: list[str] = []
    for fpath in changed:
        rel = fpath.relative_to(fix_dir)
        fix_text = fpath.read_text()
        base_file = base_dir / rel
        lines = changed_line_numbers(base_file.read_text(), fix_text) if base_file.exists() else None
        mutants = generate_mutants(fix_text, lines)
        for mid, mutated in mutants:
            total += 1
            tmp = Path(tempfile.mkdtemp(prefix="fjharden-"))
            try:
                copy_tree(task_dir / "base", tmp)
                init_base_repo(tmp)
                apply_unified_diff(tmp, task.test_patch)
                copy_tree(task_dir / "fix", tmp)          # apply gold fix
                (tmp / rel).write_text(mutated)            # splice in the mutant
                passed, total_t, _ = run_nodeids(tmp, nodeids)
                if passed < total_t:
                    killed += 1
                else:
                    survivors.append(f"{rel}:{mid}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return HardenResult(total, killed, survivors, threshold)


def main() -> None:
    """Sweep every golden task and report its mutation score (credibility check)."""
    from forgejudge.golden.build_dataset import build_task, discover_task_dirs

    rows = []
    for d in discover_task_dirs():
        task, _ = build_task(d)
        r = harden_check(task, d)
        rows.append((task.instance_id, r))
        print(
            f"  [{r.status:12s}] {task.instance_id:34s} score={r.mutation_score:5.2f} "
            f"killed={r.mutants_killed}/{r.mutants_total} survivors={len(r.survivors)}"
        )
    weak = [iid for iid, r in rows if r.status == "weak"]
    scored = [r.mutation_score for _, r in rows if r.mutants_total > 0]
    mean = sum(scored) / len(scored) if scored else 0.0
    print(f"\n{len(rows)} tasks · mean mutation score (where applicable)={mean:.2f} · weak={len(weak)} {weak}")


if __name__ == "__main__":
    main()
