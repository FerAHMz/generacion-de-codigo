"""getReg(): asignación de registros con linear scan, spill y clases de
registro (enteros / flotantes, $t / $s)."""

import pytest

from compiscript.ir.interp import run as interp_run
from compiscript.ir.liveness import LiveInterval
from compiscript.mips import MipsTranslator
from compiscript.mips.regs import (CALLEE_SAVED, CALLER_SAVED, FLOAT_POOL, FLOAT_SCRATCH, INT_POOL,
                                   INT_SCRATCH, RegisterManager, linear_scan)

from .helpers import ROOT, compile_ok, requires_mars, run_asm, translator_class

EXAMPLES = sorted((ROOT / "examples").glob("[0-9]*.cps"))

PRESSURE = """
let a: integer = 1; let b: integer = 2; let c: integer = 3; let d: integer = 4;
let e: integer = 5; let f: integer = 6; let g: integer = 7; let h: integer = 8;
print(((a + b) * (c + d)) - ((e + f) * (g + h)));
print((a + b) * (c + d) + (e + f) * (g + h) - (a + h));
"""

FACT = """
function fact(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * fact(n - 1);
}
print(fact(5));
"""


def allocate(src, **pools):
    res = compile_ok(src)
    tr = MipsTranslator(res.program, res.table, "linear")
    regs = RegisterManager(tr, res.program, res.table, "linear", **pools)
    for label, (lo, hi) in tr.functions.items():
        regs.enter_function(label, lo, hi, res.table.record_of(label))
    return res, regs


# --------------------------------------------------------------- pools

def test_scratch_registers_are_not_allocatable():
    assert not set(INT_SCRATCH) & set(INT_POOL)
    assert not set(FLOAT_SCRATCH) & set(FLOAT_POOL)
    assert "$v1" not in INT_POOL and "$at" not in INT_POOL
    assert set(INT_POOL) == set(CALLER_SAVED) | set(CALLEE_SAVED)


# --------------------------------------------------------- linear scan

def _iv(start, end, crosses=False, f=False):
    return LiveInterval("f", start, start, end, f, crosses)


def test_scan_reuses_register_when_intervals_only_touch():
    a, b = _iv(0, 3), _iv(3, 5)
    assert linear_scan([a, b], ["$t0", "$t1"]) == 0
    assert a.location == b.location == "$t0"


def test_scan_spills_the_interval_that_ends_last():
    a, b, c = _iv(0, 10), _iv(1, 4), _iv(2, 5)
    spills = linear_scan([a, b, c], ["$t0", "$t1"])
    assert spills == 1 and a.spilled and a.spill_slot == 0
    assert {b.location, c.location} == {"$t0", "$t1"}


def test_scan_prefers_s_registers_across_calls():
    a, b = _iv(0, 9, crosses=True), _iv(1, 2)
    linear_scan([a, b], INT_POOL, CALLEE_SAVED)
    assert a.location == "$s0" and b.location == "$t0"


def test_scan_falls_back_to_other_class_when_preferred_is_full():
    a, b = _iv(0, 9, crosses=True), _iv(1, 8, crosses=True)
    linear_scan([a, b], ["$t0", "$s0"], ["$s0"])
    assert a.location == "$s0" and b.location == "$t0"


# ------------------------------------------------- sobre programas reales

def _assert_no_conflicts(regs):
    for fa in regs.allocations.values():
        placed = [iv for iv in fa.intervals if iv.location]
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if a.location == b.location:
                    assert a.end <= b.start or b.end <= a.start, (fa.label, a, b)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_no_two_live_values_share_a_register(path):
    _, regs = allocate(path.read_text(encoding="utf-8"))
    _assert_no_conflicts(regs)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_no_conflicts_with_two_registers(path):
    _, regs = allocate(path.read_text(encoding="utf-8"), int_pool=("$t0", "$t1"),
                       float_pool=("$f4", "$f5"))
    _assert_no_conflicts(regs)


def test_value_alive_across_call_goes_to_s_register():
    res, regs = allocate(FACT)
    fa = regs.allocations["fact"]
    crossing = [iv for iv in fa.intervals if iv.crosses_call]
    assert crossing and all(iv.location in CALLEE_SAVED for iv in crossing)
    assert regs.callee_saved("fact") == sorted({iv.location for iv in crossing})


def test_float_and_int_classes_are_separate():
    res, regs = allocate("let x: float = 1.5; let y: integer = 2; print(x * 2.0 + 1.0); print(y + 3);")
    for iv in regs.allocations["main"].intervals:
        if iv.location:
            assert iv.location.startswith("$f") == iv.is_float


def test_main_does_not_save_s_registers():
    _, regs = allocate(FACT)
    assert regs.callee_saved("main") == []


def test_small_pool_produces_spill_slots():
    _, regs = allocate(PRESSURE, int_pool=("$t0", "$t1"))
    assert regs.spill_words("main") > 0
    _, roomy = allocate(PRESSURE)
    assert roomy.spill_words("main") == 0


def test_linear_mode_uses_registers_instead_of_slots():
    res = compile_ok("let a: integer = 2; print(a * 3 + a);")
    lin = translator_class()(res.program, res.table, "linear").translate()
    stk = translator_class()(res.program, res.table, "stack").translate()
    assert any(r.startswith("$t") and r not in INT_SCRATCH
               for _, args in lin.instructions() for r in args)
    assert not any("($fp)" in a for _, args in lin.instructions() for a in args)
    assert any("($fp)" in a for _, args in stk.instructions() for a in args)


# ------------------------------------------------------------------ MARS

def _run_with_pools(src, **pools):
    res = compile_ok(src)
    tr = translator_class()(res.program, res.table, "linear")
    tr.regs = RegisterManager(tr, res.program, res.table, "linear", **pools)
    return run_asm(tr.translate().text())


@requires_mars
def test_spilled_values_keep_the_same_output():
    res = compile_ok(PRESSURE)
    expected = interp_run(res.program, res.table)
    assert expected == ["-144", "177"]
    assert _run_with_pools(PRESSURE).lines == expected
    assert _run_with_pools(PRESSURE, int_pool=("$t0", "$t1")).lines == expected
    assert _run_with_pools(PRESSURE, int_pool=("$t0",)).lines == expected
