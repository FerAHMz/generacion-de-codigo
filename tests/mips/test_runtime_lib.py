"""Simulador (MARS desde Python) y rutinas del runtime en MIPS.

Las pruebas que ejecutan MARS usan el fixture `mars`: se saltan si no hay Java
o `tools/Mars4_5.jar` (`make mars`). Para correr solo las que no necesitan
MARS: `MARS_JAR=/no/existe pytest tests/mips`.
"""

import pytest

from compiscript.ir.runtime import MESSAGES
from compiscript.mips.simulator import (DEFAULT_STEPS, MarsResult, clean_output, mars_available,
                                        mars_command, run_mars)


@pytest.fixture
def mars():
    if not mars_available():
        pytest.skip("MARS no disponible: correr `make mars` (requiere Java)")
    return run_mars


def program(text: str, data: str = "") -> str:
    """Envuelve instrucciones en un programa con `main` que termina con la syscall 10."""
    return f"""
        .data
{data}
        .text
        .globl main
main:
{text}
        li $v0, 10
        syscall
"""


# ---------------------------------------------------------------- simulator.py

def test_comando_sin_gui_y_headless():
    cmd = mars_command("p.asm")
    assert cmd[0] == "java" and "-Djava.awt.headless=true" in cmd
    assert cmd[cmd.index("-jar") + 2:] == ["nc", "ae2", "se3", "sm", str(DEFAULT_STEPS), "p.asm"]


def test_limpia_el_ruido_de_mars():
    raw = "42\nhola\n\nProgram terminated when maximum step limit 1000 reached.\n"
    assert clean_output(raw) == ("42\nhola", True, "")
    assert clean_output("1\n2\n\n") == ("1\n2", False, "")
    out, timeout, error = clean_output("Error in /tmp/p.asm line 3 column 9: bad\n"
                                       "Processing terminated due to errors.\n")
    assert out == "" and not timeout and "line 3" in error


def test_salida_del_programa_que_empieza_con_error_no_es_ruido():
    out, _, error = clean_output("Error en tiempo de ejecución: división entre cero\n")
    assert out == "Error en tiempo de ejecución: división entre cero" and error == ""


def test_mars_result():
    r = MarsResult("1\n2", 0)
    assert r.lines == ["1", "2"] and r.ok
    assert not MarsResult("", 1).ok and not MarsResult("", 0, timeout=True).ok
    assert MarsResult("", 0).lines == []


def test_imprime_42(mars):
    res = mars(program("        li $a0, 42\n        li $v0, 1\n        syscall"))
    assert res.stdout == "42" and res.exit_code == 0 and not res.timeout


def test_codigo_de_salida_con_syscall_17(mars):
    res = mars(program("        li $a0, 7\n        li $v0, 17\n        syscall"))
    assert res.exit_code == 7


def test_bucle_infinito_termina_por_limite_de_pasos(mars):
    res = mars(program("loop:\n        j loop"), steps=10_000)
    assert res.timeout and not res.ok


def test_error_de_ensamblado(mars):
    res = mars(program("        noexiste $t0, $t1"))
    assert res.exit_code == 2 and res.error


@pytest.mark.parametrize("kind", sorted(MESSAGES))
def test_mars_imprime_los_acentos_de_los_mensajes(mars, kind):
    text = MESSAGES[kind]
    res = mars(program("        la $a0, msg\n        li $v0, 4\n        syscall",
                       data=f'msg: .asciiz "{text}"'))
    assert res.stdout == text


# --------------------------------------------------------------- runtime_lib.py

from compiscript.codegen import compile_source                       # noqa: E402
from compiscript.ir.interp import run as interp_run                   # noqa: E402
from compiscript.mips.runtime_lib import ROUTINES, standalone         # noqa: E402

PRINT_V0 = """
        move $a0, $v0
        li $v0, 4
        syscall
        li $a0, 10
        li $v0, 11
        syscall
"""


def with_routines(main: str, *names: str, data: str = "") -> str:
    rt_data, rt_code = standalone(*names)
    return program(main, data=rt_data + "\n" + data) + "\n" + rt_code + "\n"


def test_rutinas_solo_pisan_registros_permitidos():
    """Ninguna rutina escribe en registros que pueden tener temporales."""
    import re
    prohibidos = re.compile(r"\$(t[0-7]|s[0-7]|fp|f([4-9]|1[01]|1[6-9]|2\d|3[01]))\b")
    for name, code in ROUTINES.items():
        for line in code.splitlines():
            ins = line.split("#", 1)[0].strip()
            if not ins or ins.endswith(":"):
                continue
            op, _, args = ins.partition(" ")
            if op in ("sw", "sb", "s.s", "jr", "bnez", "beqz", "bne", "beq", "blt", "blez", "bgez",
                      "j", "div", "c.lt.s"):
                continue
            destino = args.split(",")[0].strip()
            assert not prohibidos.match(destino), f"{name}: {ins}"


@pytest.mark.parametrize("n", [0, 5, -7, 42, 1000000, 2147483647, -2147483648])
def test_itoa(mars, n):
    res = mars(with_routines(f"        li $a0, {n}\n        jal __itoa" + PRINT_V0, "__itoa"))
    assert res.stdout == str(n)


@pytest.mark.parametrize("value", [0.5, 2.25, 3.0, -0.125, 100.0, 0.1, 3.14159, 1234.5, -7.75, 0.0])
def test_ftoa_igual_que_la_syscall_2(mars, value):
    main = f"""
        l.s $f12, x
        li $v0, 2
        syscall
        li $a0, 10
        li $v0, 11
        syscall
        l.s $f12, x
        jal __ftoa
""" + PRINT_V0
    res = mars(with_routines(main, "__ftoa", data=f"        .align 2\nx: .float {value}"))
    syscall2, ftoa = res.lines
    assert ftoa == syscall2


@pytest.mark.parametrize("b, text", [(1, "true"), (0, "false")])
def test_btoa(mars, b, text):
    res = mars(with_routines(f"        li $a0, {b}\n        jal __btoa" + PRINT_V0, "__btoa"))
    assert res.stdout == text


def test_concat_y_null(mars):
    main = """
        la $a0, a
        la $a1, b
        jal __concat
        move $s0, $v0
""" + PRINT_V0 + """
        move $a0, $s0
        li $a1, 0
        jal __concat
""" + PRINT_V0 + """
        li $a0, 0
        la $a1, vacio
        jal __concat
""" + PRINT_V0
    res = mars(with_routines(main, "__concat",
                             data='a: .asciiz "hola "\nb: .asciiz "mundo"\nvacio: .asciiz ""'))
    assert res.lines == ["hola mundo", "hola mundonull", "null"]


def test_alloc_alinea_a_4(mars):
    main = """
        li $a0, 5
        jal __alloc
        move $s0, $v0
        li $a0, 1
        jal __alloc
        subu $a0, $v0, $s0
        li $v0, 1
        syscall
        andi $a0, $s0, 3
        li $v0, 1
        syscall
"""
    assert mars(with_routines(main, "__alloc")).stdout == "80"


CONCAT_PROGRAMS = {
    "entero": ('let n: integer = 5; print("n = " + n);', ["n = 5"]),
    "negativo_y_cero": ('let a: integer = -12; print(a + "|" + 0);', ["-12|0"]),
    "float": ('let f: float = 2.25; print("f = " + f); print(0.5 + "!");', ["f = 2.25", "0.5!"]),
    "boolean_y_null": ('let b: boolean = 3 > 2; let s: string = null; print("b=" + b + ", s=" + s);',
                       ["b=true, s=null"]),
    "en_funcion_hoja": ('function saludo(x: string): string { return "Hola " + x; }\n'
                        'print(saludo("Ana")); print(saludo("Luis") + "!");', ["Hola Ana", "Hola Luis!"]),
    "acumulado": ('let s: string = ""; let i: integer = 0;\n'
                  'while (i < 5) { s = s + i; i = i + 1; } print(s); print("len ok");',
                  ["01234", "len ok"]),
}


@pytest.mark.parametrize("mode", ["linear", "stack"])
@pytest.mark.parametrize("name", sorted(CONCAT_PROGRAMS))
def test_concat_en_programas(mars, name, mode):
    src, expected = CONCAT_PROGRAMS[name]
    res = compile_source(src, regalloc=mode)
    assert res.ok, [str(e) for e in res.errors]
    assert interp_run(res.program, res.table) == expected
    out = mars(res.asm)
    assert out.exit_code == 0 and out.lines == expected


def test_concat_traduce_con_jal_a_las_rutinas():
    asm = compile_source('let n: integer = 5; let b: boolean = true; print("n = " + n + b);').asm
    assert "jal __itoa" in asm and "jal __btoa" in asm and "jal __concat" in asm
    assert asm.count("__concat:") == 1 and '__rt_null: .asciiz "null"' in asm

