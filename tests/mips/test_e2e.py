"""Pruebas de extremo a extremo del Proyecto 3: programa .cps -> TAC -> MIPS ->
MARS, contra el intérprete de TAC (`interp.run`) como oráculo.

Cada programa se compila en los dos modos de asignación de registros
(`linear` y `stack`); la salida de MARS debe ser exactamente la del
intérprete y el código de salida 0, o 1 si el intérprete terminó por un error
en ejecución sin `try`.

Casos fallidos:
  * error sintáctico o semántico -> `compile_source(...).asm is None`;
  * error en ejecución sin `try` -> mensaje y código de salida ≠ 0;
  * bucle infinito -> MARS termina por el límite de pasos (`timeout`).

Si alguna instrucción todavía no tiene traducción (`MipsNotImplemented`), el
caso se salta; se activa solo cuando se agrega el handler. Las pruebas que
corren MARS se saltan si no hay Java o `tools/Mars4_5.jar` (`make mars`).
"""

from pathlib import Path

import pytest

from compiscript.codegen import compile_source
from compiscript.ir.interp import Interpreter
from compiscript.ir.runtime import MESSAGES, RuntimeErrorKind
from compiscript.mips import MipsNotImplemented
from compiscript.mips.simulator import mars_available, run_mars

ROOT = Path(__file__).resolve().parents[2]
MODES = ("linear", "stack")
PREFIX = "Error en tiempo de ejecución: "
DIV0 = MESSAGES[RuntimeErrorKind.DIVISION_BY_ZERO]
INDEX = MESSAGES[RuntimeErrorKind.INDEX_OUT_OF_BOUNDS]
NULL = MESSAGES[RuntimeErrorKind.NULL_REFERENCE]

FILES = sorted((ROOT / "examples").glob("[0-9]*.cps")) + sorted((ROOT / "examples" / "mips").glob("*.cps"))
FILES.append(ROOT / "program" / "program.cps")
ERROR_FILES = sorted((ROOT / "examples").glob("err_*.cps"))


@pytest.fixture
def mars():
    if not mars_available():
        pytest.skip("MARS no disponible: correr `make mars` (requiere Java)")
    return run_mars


def oracle(res):
    """(salida, código esperado) según el intérprete de TAC."""
    interp = Interpreter(res.program, res.table)
    output = interp.run()
    return output, (0 if interp.error is None else 1)


def asm_or_skip(src: str, mode: str):
    res = compile_source(src, regalloc=mode)
    assert res.ok, [str(e) for e in res.errors]
    try:
        return res, res.asm
    except MipsNotImplemented as exc:
        pytest.skip(f"todavía sin traducción a MIPS: {exc}")


def check(mars, src: str, mode: str, expected=None, code=None):
    res, asm = asm_or_skip(src, mode)
    out, exit_code = oracle(res)
    if expected is not None:
        assert out == expected, "el intérprete no da la salida esperada"
        assert exit_code == (code if code is not None else exit_code)
    run = mars(asm)
    assert not run.timeout, f"MARS no terminó:\n{run.stdout}"
    assert run.error == "", run.error
    assert run.lines == out
    assert run.exit_code == exit_code
    return run


# ------------------------------------------------------------------ ejemplos

def _id(path: Path) -> str:
    return str(path.relative_to(ROOT))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("path", FILES, ids=_id)
def test_ejemplo_igual_al_interprete(mars, path, mode):
    check(mars, path.read_text(encoding="utf-8"), mode)


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_ejemplo_genera_asm_en_ambos_modos(path):
    src = path.read_text(encoding="utf-8")
    for mode in MODES:
        _, asm = asm_or_skip(src, mode)
        assert asm.count("main:") == 1 and ".text" in asm


# ------------------------------------------------- programas cortos por tema

CASES = {
    "recursion_profunda": ("""
        function suma(n: integer): integer { if (n == 0) { return 0; } return n + suma(n - 1); }
        print(suma(500));
    """, ["125250"]),
    "closure_modifica_variable_externa": ("""
        function f(): integer {
          let x: integer = 1;
          function g(): integer { x = x * 3; return x; }
          g(); g();
          return x;
        }
        print(f());
    """, ["9"]),
    "metodo_heredado_y_sobrescrito": ("""
        class A { function quien(): string { return "A"; } function hola(): string { return "soy " + this.quien(); } }
        class B : A { function quien(): string { return "B"; } }
        let a: A = new B();
        print(a.hola());
    """, ["soy B"]),
    "matriz_escritura_y_lectura": ("""
        let m: integer[][] = [[0, 0], [0, 0]];
        for (let i: integer = 0; i < 2; i = i + 1) { for (let j: integer = 0; j < 2; j = j + 1) { m[i][j] = i * 10 + j; } }
        print(m[1][0] + m[0][1]);
    """, ["11"]),
    "strings_con_todos_los_tipos": ("""
        let s: string = "i=" + 7 + " f=" + 0.25 + " b=" + false;
        print(s);
    """, ["i=7 f=0.25 b=false"]),
    "floats_exactos": ("""
        let x: float = 0.75; let y: float = 0.125;
        print(x + y); print(x * 4); print(x / y); print(-x);
    """, ["0.875", "3.0", "6.0", "-0.75"]),
    "switch_default": ("""
        let k: integer = 9;
        switch (k) { case 1: print("uno"); break; default: print("otro"); }
    """, ["otro"]),
    "try_catch_desde_funcion": ("""
        function f(xs: integer[]): integer { return xs[10]; }
        try { print(f([1, 2])); } catch (e) { print("capturado: " + e); }
        print("sigue");
    """, ["capturado: " + INDEX, "sigue"]),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(CASES))
def test_caso(mars, name, mode):
    src, expected = CASES[name]
    check(mars, src, mode, expected, 0)


# ------------------------------------------------------------ casos fallidos

@pytest.mark.parametrize("path", ERROR_FILES, ids=_id)
def test_error_de_compilacion_no_genera_asm(path):
    for mode in MODES:
        res = compile_source(path.read_text(encoding="utf-8"), regalloc=mode)
        assert not res.ok and res.errors
        assert res.asm is None and res.to_dict()["mips"] == []


@pytest.mark.parametrize("src", ["let x: integer = ;", 'let x: integer = "a";', "print(noExiste);"])
def test_error_sintactico_o_semantico_no_genera_asm(src):
    assert compile_source(src).asm is None


RUNTIME_ERRORS = {
    "division_entre_cero": ('print("a"); let z: integer = 0; print(10 / z); print("b");', ["a", PREFIX + DIV0]),
    "indice_fuera_de_rango": ('let xs: integer[] = [1, 2]; print(xs[2]);', [PREFIX + INDEX]),
    "indice_negativo": ('let xs: integer[] = [1, 2]; let i: integer = -1; print(xs[i]);', [PREFIX + INDEX]),
    "referencia_null": ('class P { let x: integer; } let p: P = null; print("x"); print(p.x);',
                        ["x", PREFIX + NULL]),
    "error_en_funcion_sin_try": ("""
        function g(n: integer): integer { return 100 / n; }
        function f(n: integer): integer { return g(n - 1); }
        print(f(2)); print(f(1));
    """, ["100", PREFIX + DIV0]),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(RUNTIME_ERRORS))
def test_error_en_ejecucion_sin_try(mars, name, mode):
    src, expected = RUNTIME_ERRORS[name]
    run = check(mars, src, mode, expected, 1)
    assert run.exit_code != 0


@pytest.mark.parametrize("mode", MODES)
def test_bucle_infinito_termina_por_limite_de_pasos(mars, mode):
    _, asm = asm_or_skip('let i: integer = 0; print("inicio"); while (true) { i = i + 1; }', mode)
    run = mars(asm, steps=200_000)
    assert run.timeout and run.lines == ["inicio"]
