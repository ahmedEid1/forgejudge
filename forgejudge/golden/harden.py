"""Mutation hardening: prove a golden task's tests would catch a wrong fix.

We generate single-point mutants of the gold-fixed source (the files in
``fix/``), splice each into an otherwise-correct materialized tree, and run the
task's FAIL_TO_PASS + PASS_TO_PASS suite. A mutant is *killed* if any test
fails. A high kill rate means the tests genuinely constrain behaviour; surviving
mutants reveal weak tests (the documented ~31% weak-test failure mode).
"""

import ast
import copy
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
    """Count mutable nodes in deterministic traversal order."""

    def __init__(self) -> None:
        self.n = 0

    def visit_Compare(self, node: ast.Compare) -> None:
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP:
            self.n += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if type(node.op) in _BIN:
            self.n += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if type(node.op) in _BOOL:
            self.n += 1
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (bool, int)):
            self.n += 1
        self.generic_visit(node)


class _Mutator(ast.NodeTransformer):
    """Apply exactly the ``target``-th mutation (same order as :class:`_Counter`)."""

    def __init__(self, target: int) -> None:
        self.i = -1
        self.target = target
        self.applied = False

    def _hit(self) -> bool:
        self.i += 1
        return self.i == self.target

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP and self._hit():
            node.ops = [_CMP[type(node.ops[0])]()]
            self.applied = True
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if type(node.op) in _BIN and self._hit():
            node.op = _BIN[type(node.op)]()
            self.applied = True
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if type(node.op) in _BOOL and self._hit():
            node.op = _BOOL[type(node.op)]()
            self.applied = True
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        self.generic_visit(node)
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


def generate_mutants(source: str) -> list[tuple[str, str]]:
    """Return ``[(mutant_id, mutated_source), ...]`` — one single-point mutant each."""
    tree = ast.parse(source)
    counter = _Counter()
    counter.visit(tree)
    mutants: list[tuple[str, str]] = []
    for i in range(counter.n):
        m = _Mutator(i)
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
    def passed(self) -> bool:
        return self.mutants_total > 0 and self.mutants_killed > 0 and self.mutation_score >= self.threshold


def harden_check(task: Task, task_dir: str | Path, *, threshold: float = 0.5) -> HardenResult:
    """Mutate each gold-fixed source file and check the task's tests kill them."""
    task_dir = Path(task_dir)
    fix_dir = task_dir / "fix"
    changed = sorted(p for p in fix_dir.rglob("*.py"))
    nodeids = list(task.fail_to_pass) + list(task.pass_to_pass)

    total = 0
    killed = 0
    survivors: list[str] = []
    for fpath in changed:
        rel = fpath.relative_to(fix_dir)
        mutants = generate_mutants(fpath.read_text())
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
