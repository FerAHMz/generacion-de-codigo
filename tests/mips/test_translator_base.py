"""Base de la generación de MIPS: programa, despacho por instrucción, modo
pila de getReg() y la rutina __raise provisional."""

import pytest

from compiscript.codegen import compile_source
from compiscript.ir.tac import Const, Op, Quad, TACProgram, Temp
from compiscript.mips import MipsNotImplemented, MipsProgram, MipsTranslator
from compiscript.mips.regs import FLOAT_SCRATCH, INT_SCRATCH, RegisterManager
from compiscript.mips.translator import handler_name
from compiscript.types import FLOAT, INTEGER

from .helpers import compile_ok, requires_mars, run_asm, run_source, translate


# ------------------------------------------------------------------ programa

def test_string_interned_and_escaped():
    asm = MipsProgram()
    a = asm.string('di "hola"\n')
    b = asm.string('di "hola"\n')
    assert a == b
    assert f'{a}: .asciiz "di \\"hola\\"\\n"' in asm.text()


def test_float_constant_and_word_alignment():
    asm = MipsProgram()
    asm.string("x")
    label = asm.float_const(2.5)
    lines = asm.lines()
    i = lines.index(f"{label}: .float 2.5")
    assert lines[i - 1].strip() == ".align 2"


def test_routine_added_once_at_the_end():
    asm = MipsProgram()
    asm.label("main")
    asm.add_routine("__r", "__r:\n jr $ra")
    asm.add_routine("__r", "__r:\n otra")
    text = asm.text()
    assert text.count("__r:") == 1 and text.index("main:") < text.index("__r:")


def test_instructions_parses_text_segment():
    asm = MipsProgram()
    asm.label("main")
    asm.emit("addiu", "$sp", "$sp", -8, comment="x")
    assert asm.instructions() == [("addiu", ("$sp", "$sp", "-8"))]


# ----------------------------------------------------------------- despacho

@pytest.mark.parametrize("op, name", [
    (Op.ADD, "op_add"), (Op.INDEX_SET, "op_index_set"), ("if<", "op_if_lt"),
    ("if!=", "op_if_ne"), (Op.FUNC_BEGIN, "op_func_begin"), (Op.GET_EXCEPTION, "op_get_exception"),
])
def test_handler_names(op, name):
    assert handler_name(op) == name


def test_missing_handler_raises_not_implemented():
    res = compile_ok("")
    prog = TACProgram(list(res.program) )
    prog.quads.insert(1, Quad("bogus", Const(1)))
    with pytest.raises(MipsNotImplemented):
        MipsTranslator(prog, res.table).translate()


def test_semantic_error_has_no_asm():
    res = compile_source("let x: integer = true;")
    assert not res.ok and res.asm is None and res.to_dict()["mips"] == []


def test_empty_program_main_and_exit():
    res = compile_ok("")
    text = res.asm
    assert "main:" in text and ".globl main" in text
    assert text.rstrip().endswith("# exit")


# --------------------------------------------------------- getReg modo pila

def _manager():
    res = compile_ok("")
    tr = MipsTranslator(res.program, res.table, "stack")
    main = res.table.main
    tr.regs.enter_function("main", 0, len(res.program) - 1, main)
    tr.regs.begin(0)
    return tr


def test_stack_mode_loads_temp_from_its_slot():
    tr = _manager()
    reg = tr.regs.get_reg(0, Temp(3, INTEGER), "use")
    assert reg == INT_SCRATCH[0]
    off = -(tr.table.main.temps_base + 3 * 4)
    assert tr.asm.instructions()[-1] == ("lw", ("$t8", f"{off}($fp)"))


def test_stack_mode_def_goes_to_scratch_and_is_stored():
    tr = _manager()
    t = Temp(2, FLOAT)
    reg = tr.regs.dest(t, 0)
    assert reg == FLOAT_SCRATCH[0]
    tr.regs.store(reg, t, 0)
    assert tr.asm.instructions()[-1][0] == "s.s"


def test_scratch_registers_rotate_within_an_instruction():
    tr = _manager()
    regs = [tr.regs.load(Const(i), 0) for i in range(3)]
    assert regs == list(INT_SCRATCH)
    tr.regs.begin(1)
    assert tr.regs.load(Const(9), 1) == INT_SCRATCH[0]


def test_constants_by_kind():
    tr = _manager()
    tr.regs.load(Const(None), 0)
    tr.regs.load(Const(True), 0)
    tr.regs.begin(1)
    tr.regs.load(Const(1.5), 1)
    tr.regs.load(Const("hola"), 1)
    ops = [o for o, _ in tr.asm.instructions()]
    assert ops == ["move", "li", "l.s", "la"]


# ------------------------------------------------------------------- MARS

@requires_mars
def test_empty_program_runs_in_mars():
    run = run_asm(compile_ok("").asm, registers=["$sp"])
    assert run.lines == [] and run.exit_code == 0
    assert run.registers["$sp"] == 0x7FFFEFFC


@requires_mars
def test_print_constant_runs_in_mars():
    run, expected = run_source("print(5);\nprint(\"hola\");")
    assert run.lines == expected == ["5", "hola"]


@requires_mars
def test_provisional_raise_prints_message_and_exits_1():
    res = compile_ok("")
    tr = MipsTranslator(res.program, res.table)
    tr.asm.label("main")
    tr.runtime_error("division_by_zero")
    run = run_asm(tr.asm.text())
    assert run.lines == ["Error en tiempo de ejecución: división entre cero"]
    assert run.exit_code == 1
