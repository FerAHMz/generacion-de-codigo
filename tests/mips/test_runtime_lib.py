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

