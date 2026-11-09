"""Traducción de relacionales, saltos y `print` (Felipe Aguilar).

Los programas de MARS son los ejemplos de docs/LENGUAJE_INTERMEDIO.md
§7.4–7.10 (corto circuito, bucles, foreach, switch, break/continue, ternario)
y deben dar la misma salida que el intérprete de TAC en los dos modos."""

import pytest

from compiscript.ir.interp import run as interp_run
from compiscript.mips import MODES

from .helpers import requires_mars, run_asm, translate


def instrs(src, mode="stack"):
    return translate(src, mode)[1].instructions()


def mnemonics(src, mode="stack"):
    return [o for o, _ in instrs(src, mode)]


def mars_matches(src, mode):
    res, prog = translate(src, mode)
    run = run_asm(prog.text())
    assert run.exit_code == 0, run.raw
    expected = interp_run(res.program, res.table)
    assert run.lines == expected
    return run.lines


# ------------------------------------------------------------------ texto

@pytest.mark.parametrize("relop, mnemonic", [
    ("<", "slt"), ("<=", "sle"), (">", "sgt"), (">=", "sge"), ("==", "seq"), ("!=", "sne"),
])
def test_integer_relational_with_value(relop, mnemonic):
    assert mnemonic in mnemonics(f"let a = 1; let b = 2; let c = a {relop} b; print(c);")


@pytest.mark.parametrize("relop, cmp, branch", [
    ("<", "c.lt.s", "bc1t"), ("<=", "c.le.s", "bc1t"), (">", "c.lt.s", "bc1t"),
    (">=", "c.le.s", "bc1t"), ("==", "c.eq.s", "bc1t"), ("!=", "c.eq.s", "bc1f"),
])
def test_float_relational_with_value(relop, cmp, branch):
    seq = instrs(f"let a: float = 1.5; let b: float = 2.5; let c = a {relop} b; print(c);")
    ops = [o for o, _ in seq]
    i = ops.index(cmp)
    assert ops[i + 1:i + 4] == ["li", branch, "li"]


def test_float_greater_swaps_operands():
    seq = instrs("let a: float = 1.5; let b: float = 2.5; let c = a > b; print(c);")
    assert ("c.lt.s", ("$f31", "$f30")) in seq


# El generador salta al `else` con la condición negada: `if (a < 2)` -> `if t1 >= 2 goto L`.
@pytest.mark.parametrize("relop, mnemonic", [
    ("<", "bge"), ("<=", "bgt"), (">", "ble"), (">=", "blt"), ("==", "bne"), ("!=", "beq"),
])
def test_conditional_jumps(relop, mnemonic):
    assert mnemonic in mnemonics(f"let a = 1; if (a {relop} 2) {{ print(1); }}")


@pytest.mark.parametrize("relop, cmp, branch", [
    ("<", "c.le.s", "bc1t"), (">=", "c.lt.s", "bc1t"), ("==", "c.eq.s", "bc1f"), ("!=", "c.eq.s", "bc1t"),
])
def test_float_conditional_jump(relop, cmp, branch):
    ops = mnemonics(f"let a: float = 1.5; if (a {relop} 2.0) {{ print(1); }}")
    i = ops.index(cmp)
    assert ops[i + 1] == branch


def test_print_syscalls_by_type():
    prog = translate('print(1); print(1.5); print("s"); print(true);')[1]
    li_v0 = [a[1] for o, a in prog.instructions() if o == "li" and a[0] == "$v0"]
    assert li_v0 == ["1", "11", "2", "11", "4", "11", "4", "11", "10"]   # 10: exit
    assert '"true"' in prog.text() and '"false"' in prog.text()


# ------------------------------------------------------------------- MARS

PROGRAMS = {
    "relacionales": """
let a = 3; let b = 5;
print(a < b); print(a <= b); print(a > b); print(a >= b); print(a == b); print(a != b);
let x: float = 1.5; let y: float = 1.5;
print(x < y); print(x <= y); print(x > y); print(x >= y); print(x == y); print(x != y);
let z: float = 0.25;
if (z < x) { print("z < x"); }
if (x >= z) { print("x >= z"); }
if (x == y) { print("x == y"); }
if (x != z) { print("x != z"); }
""",
    "corto_circuito": """
let a = true; let b = false; let n = 5;
if (a && !b) { print("and"); }
if (b || n > 3) { print("or"); }
if (!(a && b) || b) { print("not"); }
let c = (n > 1 && n < 10) || b;
print(c);
let d = a && b;
print(d);
""",
    "if_else": """
let n = 7;
if (n % 2 == 0) { print("par"); } else { print("impar"); }
if (n > 10) { print("grande"); } else { if (n > 5) { print("mediano"); } else { print("chico"); } }
""",
    "bucles": """
let i = 0; let s = 0;
while (i < 5) { s = s + i; i = i + 1; }
print(s);
do { i = i - 2; } while (i > 0);
print(i);
for (let j: integer = 0; j < 3; j = j + 1) { print(j); }
let k: float = 0.0;
while (k < 1.0) { k = k + 0.25; }
print(k);
""",
    "break_continue": """
for (let j: integer = 0; j < 10; j = j + 1) {
  if (j == 2) { continue; }
  if (j == 5) { break; }
  print(j);
}
""",
    "switch": """
let x = 2;
switch (x) {
  case 1: print("uno");
  case 2: print("dos");
  case 3: print("tres"); break;
  default: print("otro");
}
switch (9) { case 1: print("uno"); default: print("default"); }
""",
    "ternario": """
let n = 4;
let m = n > 3 ? n * 2 : n - 1;
print(m);
let f: float = n < 3 ? 1.5 : 2.5;
print(f);
print(n == 4 ? "cuatro" : "otro");
""",
    "print_por_tipo": """
print(42); print(-7); print(2.5); print(-0.5); print("texto"); print(true); print(false);
let b = 3 > 2; print(b);
let s: string = "hola"; print(s);
""",
    "strings_iguales": """
let a = "hola"; let b = "hola"; let c = "adiós";
print(a == b); print(a != b); print(a == c); print(a != c);
if (a == "hola") { print("igual"); }
if (c != "hola") { print("distinto"); }
""",
}


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_control_programs_match_interpreter(name, mode):
    mars_matches(PROGRAMS[name], mode)


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_switch_fallthrough_output(mode):
    assert mars_matches(PROGRAMS["switch"], mode) == ["dos", "tres", "default"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_float_relationals_output(mode):
    out = mars_matches(PROGRAMS["relacionales"], mode)
    assert out[6:12] == ["false", "true", "false", "true", "true", "false"]
