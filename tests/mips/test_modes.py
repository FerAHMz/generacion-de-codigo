"""Modo `linear` contra modo `stack`: los dos deben producir exactamente la
misma salida que el intérprete de TAC en todos los programas.

Los ejemplos que usan instrucciones que todavía no tienen traducción a MIPS se
marcan como skip y se activan solos cuando se agrega su handler."""

import pytest

from compiscript.codegen import compile_source
from compiscript.ir.interp import run as interp_run
from compiscript.mips import MODES as ALL_MODES, MipsNotImplemented

from .helpers import MODES, ROOT, compile_ok, requires_mars, run_asm, translator_class
from .test_calls import PROGRAMS

EXAMPLES = sorted((ROOT / "examples").glob("[0-9]*.cps"))
CASES = {p.name: p.read_text(encoding="utf-8") for p in EXAMPLES}
CASES.update({f"llamadas/{k}": v for k, v in PROGRAMS.items()})


def asm_or_skip(src, mode):
    res = compile_ok(src, mode)
    try:
        prog = translator_class()(res.program, res.table, mode).translate()
    except MipsNotImplemented as exc:
        pytest.skip(f"todavía sin traducción: {exc}")
    return res, prog


def test_modes_available():
    assert set(ALL_MODES) == {"linear", "stack"}


def test_unknown_mode_is_rejected():
    res = compile_source("print(1);", regalloc="registros")
    with pytest.raises(ValueError):
        res.asm


@pytest.mark.parametrize("name", sorted(CASES))
def test_linear_uses_fewer_memory_accesses_than_stack(name):
    _, lin = asm_or_skip(CASES[name], "linear")
    _, stk = asm_or_skip(CASES[name], "stack")
    mem = lambda prog: sum(1 for o, a in prog.instructions()
                           if o in ("lw", "sw", "l.s", "s.s") and a and a[-1].endswith("($fp)"))
    assert mem(lin) <= mem(stk)


@requires_mars
@pytest.mark.parametrize("name", sorted(CASES))
def test_both_modes_give_the_interpreter_output(name):
    outputs = {}
    for mode in MODES:
        res, prog = asm_or_skip(CASES[name], mode)
        run = run_asm(prog.text())
        assert run.exit_code == 0, run.raw
        outputs[mode] = run.lines
    assert outputs["linear"] == outputs["stack"] == interp_run(res.program, res.table)
