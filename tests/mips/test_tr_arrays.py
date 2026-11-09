"""Traducción de arreglos: `alloc`, `len`, `[]` y `[]=` con revisión de null y
de índice (Felipe Aguilar)."""

import pytest

from compiscript.ir.interp import run as interp_run
from compiscript.mips import MODES

from .helpers import requires_mars, run_asm, translate

ERROR_INDEX = "Error en tiempo de ejecución: índice fuera de rango"
ERROR_NULL = "Error en tiempo de ejecución: acceso a una referencia null"


def mars_matches(src, mode, exit_code=0):
    res, prog = translate(src, mode)
    run = run_asm(prog.text())
    assert run.exit_code == exit_code, run.raw
    assert run.lines == interp_run(res.program, res.table)
    return run.lines


def ops(src, mode="stack"):
    return [o for o, _ in translate(src, mode)[1].instructions()]


# ------------------------------------------------------------------ texto

def test_alloc_uses_sbrk_and_stores_length():
    prog = translate("let xs = [1, 2, 3]; print(xs[0]);")[1]
    seq = prog.instructions()
    i = seq.index(("li", ("$a0", "16")))           # 4 + 4·3 bytes
    assert seq[i + 1] == ("li", ("$v0", "9")) and seq[i + 2][0] == "syscall"
    assert ("sw", ("$v1", "0($v0)")) in seq[i:i + 6]


@pytest.mark.parametrize("mode", MODES)
def test_index_get_checks_null_and_bounds_before_lw(mode):
    seq = ops("let xs = [1, 2]; let i = 1; print(xs[i]);", mode)
    start = max(k for k, o in enumerate(seq) if o == "sltu")
    before = seq[:start]
    assert "bnez" in before[-6:]                     # null
    after = seq[start:]
    assert after[:2] == ["sltu", "bnez"]             # 0 <= i < len (sin signo)
    assert after.index("lw") > after.index("addu")


def test_index_set_checks_before_sw():
    seq = ops("let xs = [1, 2]; let i = 1; xs[i] = 5; print(xs[1]);")
    last_sltu = max(k for k, o in enumerate(seq) if o == "sltu")
    assert "sw" in seq[last_sltu:] and seq[last_sltu + 1] == "bnez"


def test_float_elements_use_l_s_and_s_s():
    seq = ops("let xs: float[] = [1.5, 2.5]; print(xs[1]);")
    assert "s.s" in seq and "l.s" in seq


def test_len_checks_null():
    prog = translate("let xs = [1, 2]; foreach (x in xs) { print(x); }")[1]
    assert "__err_null_reference" in prog.text()


# ------------------------------------------------------------------- MARS

OK = {
    "foreach": """
let xs = [10, 20, 30];
foreach (x in xs) { print(x); }
let total = 0;
foreach (x in xs) { total = total + x; }
print(total);
""",
    "matriz": """
let m: integer[][] = [[1, 2, 3], [4, 5, 6]];
print(m[1][0]);
m[0][2] = 9;
let s = 0;
foreach (fila in m) { foreach (v in fila) { s = s + v; } }
print(s);
print(m[0][2]);
""",
    "float_y_boolean": """
let fs: float[] = [1.5, 2.5, 3];
fs[0] = fs[1] + fs[2];
print(fs[0]);
let bs: boolean[] = [true, false];
print(bs[0]); print(bs[1]);
""",
    "strings": """
let ws: string[] = ["a", "b"];
ws[1] = "c";
foreach (w in ws) { print(w); }
""",
    "en_funcion": """
function suma(xs: integer[]): integer {
  let s = 0;
  for (let i: integer = 0; i < 3; i = i + 1) { s = s + xs[i]; }
  return s;
}
let ys = [4, 5, 6];
print(suma(ys));
ys[2] = 0;
print(suma(ys));
""",
}

FAIL = {
    "indice_grande": ("let xs = [1, 2]; print(xs[0]); print(xs[2]); print(9);", ERROR_INDEX),
    "indice_negativo": ("let xs = [1, 2]; let i = 0 - 1; print(xs[i]);", ERROR_INDEX),
    "escritura_fuera": ("let xs = [1, 2]; xs[5] = 1;", ERROR_INDEX),
    "matriz_fuera": ("let m: integer[][] = [[1], [2]]; print(m[1][1]);", ERROR_INDEX),
}


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(OK))
def test_array_programs_match_interpreter(name, mode):
    mars_matches(OK[name], mode)


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_matrix_output(mode):
    assert mars_matches(OK["matriz"], mode) == ["4", "27", "9"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(FAIL))
def test_out_of_bounds_stops_with_the_message(name, mode):
    src, message = FAIL[name]
    out = mars_matches(src, mode, exit_code=1)
    assert out[-1] == message


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_null_array_access_is_an_error(mode):
    src = "class C { let xs: integer[]; }\nlet c: C = new C();\nprint(1);\nprint(c.xs[0]);"
    out = mars_matches(src, mode, exit_code=1)
    assert out == ["1", ERROR_NULL]
