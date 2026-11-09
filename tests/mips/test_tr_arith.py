"""Traducción de la aritmética entera y float, copias, `minus`, `not` e
`int_to_float` (Felipe Aguilar).

Dos niveles: el .asm contiene la secuencia esperada y, en MARS, la salida
coincide con la del intérprete de TAC en los modos `linear` y `stack`."""

import pytest

from compiscript.mips import MODES

from compiscript.ir.interp import run as interp_run
from compiscript.ir.tac import Op
from compiscript.mips import MipsTranslator

from .helpers import compile_ok, requires_mars, run_asm, translate


def mars_matches(src, mode, exit_code=0):
    """Ejecuta `src` en MARS y compara con el intérprete; devuelve la salida."""
    res, prog = translate(src, mode)
    run = run_asm(prog.text())
    expected = interp_run(res.program, res.table)
    assert run.exit_code == exit_code, run.raw
    assert run.lines == expected
    return run.lines


def ops(src, mode="stack"):
    return [o for o, _ in translate(src, mode)[1].instructions()]


def contains_sequence(seq, wanted):
    """`wanted` aparece en `seq` en ese orden (no necesariamente contiguo)."""
    it = iter(seq)
    return all(w in it for w in wanted)


# ------------------------------------------------------------------ texto

@pytest.mark.parametrize("mode", MODES)
def test_integer_division_uses_div_and_mflo_after_zero_check(mode):
    seq = ops("let a = 7; let b = 2; print(a / b);", mode)
    assert contains_sequence(seq, ["bnez", "la", "j", "div", "mflo"])


@pytest.mark.parametrize("mode", MODES)
def test_modulo_uses_mfhi(mode):
    seq = ops("let a = 7; let b = 2; print(a % b);", mode)
    assert contains_sequence(seq, ["bnez", "div", "mfhi"])


def test_integer_ops_mnemonics():
    seq = ops("let a = 7; let b = 2; print(a + b); print(a - b); print(a * b); print(-a);")
    assert contains_sequence(seq, ["addu", "subu", "mul", "subu"])


def test_float_ops_mnemonics():
    seq = ops("let a: float = 7.5; let b: float = 2.5;"
              "print(a + b); print(a - b); print(a * b); print(a / b); print(-a);")
    assert contains_sequence(seq, ["add.s", "sub.s", "mul.s", "mfc1", "div.s", "neg.s"])


def test_float_constants_come_from_data():
    _, prog = translate("let a: float = 2.5; print(a);")
    label = next(ln.split(":")[0] for ln in prog.lines() if ".float 2.5" in ln)
    assert ("l.s", ("$f30", label)) in [(o, a[:2]) for o, a in prog.instructions()]


def test_int_to_float_uses_mtc1_and_cvt():
    seq = ops("let n = 4; let f: float = n * 2.5; print(f);")
    assert contains_sequence(seq, ["mtc1", "cvt.s.w", "mul.s"])


def program_with_not(mode):
    """`b = a` reemplazado por `b = not a` (el generador usa saltos para `!`)."""
    res = compile_ok("let a = true; let b = a; print(b); print(a);", mode)
    for q in res.program:
        if q.op == Op.ASSIGN and str(q.result) == "b":
            q.op = Op.NOT
    return res, MipsTranslator(res.program, res.table, mode).translate()


@pytest.mark.parametrize("mode", MODES)
def test_not_uses_xori(mode):
    _, prog = program_with_not(mode)
    assert ("xori" in [o for o, _ in prog.instructions()])


def test_division_has_no_check_for_other_ops():
    res, prog = translate("let a = 7; let b = 2; print(a + b);")
    assert "__err_division_by_zero" not in prog.text()


# ------------------------------------------------------------------- MARS

ARITH = """
let a = 7;
let b = -2;
print(a / b);
print(a % b);
print(-7 / 2);
print(-7 % 2);
print(a * b + 3 - a);
print(-a);
let big = 2147483647;
print(big + 1);
"""

FLOATS = """
let x: float = 7.5;
let y: float = 2.5;
print(x + y);
print(x - y);
print(x * y);
print(x / y);
print(-x);
let n = 3;
let z: float = n;
print(z + 0.5);
let w: float = n * 1.5;
print(w);
"""

COPIES = """
let a = 5;
let b = a;
a = 9;
print(b);
let t = true;
let f = !t;
print(f);
print(!f);
let s = "hola";
let r = s;
print(r);
"""


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_integer_arithmetic_matches_interpreter(mode):
    out = mars_matches(ARITH, mode)
    assert out[:4] == ["-3", "1", "-3", "-1"]
    assert out[-1] == "-2147483648"


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_float_arithmetic_matches_interpreter(mode):
    out = mars_matches(FLOATS, mode)
    assert out == ["10.0", "5.0", "18.75", "3.0", "-7.5", "3.5", "4.5"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_copies_and_not(mode):
    assert mars_matches(COPIES, mode) == ["5", "false", "true", "hola"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_not_runs_in_mars(mode):
    res, prog = program_with_not(mode)
    run = run_asm(prog.text())
    assert run.lines == interp_run(res.program, res.table) == ["false", "true"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("expr", ["1 / 0", "5 % 0", "1.5 / 0.0"])
def test_division_by_zero_without_try_prints_the_message(mode, expr):
    src = f"let z = 0; print(\"antes\"); print({expr}); print(\"después\");"
    out = mars_matches(src, mode, exit_code=1)
    assert out == ["antes", "Error en tiempo de ejecución: división entre cero"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_division_by_zero_with_variable_divisor(mode):
    src = "function f(a: integer, b: integer): integer { return a / b; }\nprint(f(9, 3));\nprint(f(1, 0));"
    out = mars_matches(src, mode, exit_code=1)
    assert out == ["3", "Error en tiempo de ejecución: división entre cero"]
