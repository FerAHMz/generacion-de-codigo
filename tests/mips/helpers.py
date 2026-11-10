"""Utilidades de las pruebas de MIPS.

* `run_asm(texto)` ejecuta un .asm en MARS con el mismo comando que
  `compiscript.mips.simulator` (Java headless: sin ventana ni ícono) y devuelve
  la salida, el código de salida y, si se piden, los valores finales de registros.
* `translate` / `run_source` compilan con el traductor real en cualquier modo.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

from compiscript.codegen import compile_source
from compiscript.ir.interp import run as interp_run
from compiscript.mips import MipsTranslator
from compiscript.mips.simulator import ROOT, mars_available, mars_command

MODES = ("stack", "linear")

requires_mars = pytest.mark.skipif(not mars_available(),
                                   reason="MARS no disponible: correr `make mars` (requiere Java)")

_REG_LINE = re.compile(r"^(\$\w+)\t(0x[0-9a-fA-F]+)$")


@dataclass
class MarsRun:
    lines: List[str]
    exit_code: int
    registers: Dict[str, int] = field(default_factory=dict)
    step_limit: bool = False
    raw: str = ""


def run_asm(asm: str, steps: int = 2_000_000, registers: Sequence[str] = ()) -> MarsRun:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "programa.asm"
        path.write_text(asm, encoding="utf-8")
        cmd = mars_command(str(path), steps)
        cmd[-1:-1] = list(registers)          # los registros a imprimir van antes del archivo
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    raw = proc.stdout
    if proc.returncode == 2 or "Error in" in raw and "assemble" in raw.lower():
        raise AssertionError(f"MARS no pudo ensamblar el programa:\n{raw}{proc.stderr}")
    lines = raw.split("\n")
    regs: Dict[str, int] = {}
    while lines and lines[-1] == "":
        lines.pop()
    while lines and (m := _REG_LINE.match(lines[-1])):
        regs[m.group(1)] = int(m.group(2), 16)
        lines.pop()
    limit = False
    out = [ln for ln in lines]
    for i, ln in enumerate(out):
        if ln.startswith("Program terminated when maximum step limit"):
            limit = True
            out = out[:i]
            break
    while out and out[-1] == "":
        out.pop()
    return MarsRun(out, proc.returncode, regs, limit, raw)


def translator_class():
    """Traductor que usan las pruebas (hoy, el real)."""
    return MipsTranslator


def compile_ok(src: str, regalloc: str = "stack"):
    res = compile_source(src, regalloc=regalloc)
    assert res.ok, [str(e) for e in res.errors]
    return res


def translate(src: str, regalloc: str = "stack"):
    """(CompileResult, MipsProgram) con el traductor real."""
    res = compile_ok(src, regalloc)
    return res, translator_class()(res.program, res.table, regalloc).translate()


def run_source(src: str, regalloc: str = "stack", registers: Sequence[str] = ()):
    """Compila, ejecuta en MARS y devuelve (MarsRun, salida del intérprete de TAC)."""
    res, prog = translate(src, regalloc)
    return run_asm(prog.text(), registers=registers), interp_run(res.program, res.table)
