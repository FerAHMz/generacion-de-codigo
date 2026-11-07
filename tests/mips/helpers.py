"""Utilidades de las pruebas de MIPS.

* `run_asm(texto)` ejecuta un .asm en MARS (sin GUI) y devuelve la salida, el
  código de salida y, si se piden, los valores finales de registros.
* `translator_class()` arma un traductor para las pruebas de llamadas y
  registros: usa los handlers reales que ya existan y, para las instrucciones
  que todavía no se traducen, una versión mínima (solo enteros, booleanos y
  strings literales). Así estas pruebas no dependen del avance de los demás
  módulos; cuando el handler real existe, se usa ese.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

from compiscript.codegen import compile_source
from compiscript.ir.interp import run as interp_run
from compiscript.mips import MipsTranslator

ROOT = Path(__file__).resolve().parents[2]
MARS_JAR = Path(os.environ.get("MARS_JAR", ROOT / "tools" / "Mars4_5.jar"))
MODES = ("stack", "linear")


def mars_available() -> bool:
    return MARS_JAR.exists() and shutil.which("java") is not None


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
        cmd = ["java", "-jar", str(MARS_JAR), "nc", "ae2", "se3", "sm", str(steps), *registers, str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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


# ---------------------------------------------------------------------------
# Handlers mínimos para las pruebas (solo se usan si el real no existe)
# ---------------------------------------------------------------------------

def _binary(mnemonic):
    def handler(self, q, pos):
        a = self.regs.load(q.arg1, pos)
        b = self.regs.load(q.arg2, pos)
        d = self.regs.dest(q.result, pos)
        self.asm.emit(mnemonic, d, a, b)
        self.regs.store(d, q.result, pos)
    return handler


def _branch(mnemonic):
    def handler(self, q, pos):
        a = self.regs.load(q.arg1, pos)
        b = self.regs.load(q.arg2, pos)
        self.asm.emit(mnemonic, a, b, q.result.name)
    return handler


def _assign(self, q, pos):
    src = self.regs.load(q.arg1, pos)
    if q.result.is_float:
        d = self.regs.dest(q.result, pos)
        if d != src:
            self.asm.emit("mov.s", d, src)
    else:
        d = self.regs.dest(q.result, pos)
        if d != src:
            self.asm.emit("move", d, src)
    self.regs.store(d, q.result, pos)


def _print(self, q, pos):
    from compiscript.ir.tac import Const
    from compiscript.types import BOOLEAN, STRING
    a = q.arg1
    typ = getattr(a, "type", None)
    if isinstance(a, Const) and isinstance(a.value, str) or typ == STRING:
        self.asm.emit("move", "$a0", self.regs.load(a, pos))
        self.asm.emit("li", "$v0", 4)
        self.asm.emit("syscall")
    elif isinstance(a, Const) and isinstance(a.value, bool) or typ == BOOLEAN:
        r = self.regs.load(a, pos)
        yes, no = self.asm.string("true"), self.asm.string("false")
        self.asm.emit("la", "$a0", yes)
        skip = self.new_label("pb")
        self.asm.emit("bnez", r, skip)
        self.asm.emit("la", "$a0", no)
        self.asm.label(skip)
        self.asm.emit("li", "$v0", 4)
        self.asm.emit("syscall")
    elif a.is_float:
        self.asm.emit("mov.s", "$f12", self.regs.load(a, pos))
        self.asm.emit("li", "$v0", 2)
        self.asm.emit("syscall")
    else:
        self.asm.emit("move", "$a0", self.regs.load(a, pos))
        self.asm.emit("li", "$v0", 1)
        self.asm.emit("syscall")
    self.asm.emit("li", "$a0", 10)
    self.asm.emit("li", "$v0", 11)
    self.asm.emit("syscall")


def _if(self, q, pos):
    self.asm.emit("bnez", self.regs.load(q.arg1, pos), q.result.name)


def _if_false(self, q, pos):
    self.asm.emit("beqz", self.regs.load(q.arg1, pos), q.result.name)


def _relational(mnemonic):
    return _binary(mnemonic)


SUPPORT = {
    "op_assign": _assign,
    "op_add": _binary("addu"), "op_sub": _binary("subu"), "op_mul": _binary("mul"),
    "op_lt": _relational("slt"), "op_le": _relational("sle"), "op_gt": _relational("sgt"),
    "op_ge": _relational("sge"), "op_eq": _relational("seq"), "op_ne": _relational("sne"),
    "op_if_lt": _branch("blt"), "op_if_le": _branch("ble"), "op_if_gt": _branch("bgt"),
    "op_if_ge": _branch("bge"), "op_if_eq": _branch("beq"), "op_if_ne": _branch("bne"),
    "op_if": _if, "op_if_false": _if_false,
    "op_goto": lambda self, q, pos: self.asm.emit("j", q.result.name),
    "op_label": lambda self, q, pos: self.asm.label(q.result.name),
    "op_print": _print,
}


def translator_class():
    attrs = {name: fn for name, fn in SUPPORT.items() if not hasattr(MipsTranslator, name)}
    return type("TestTranslator", (MipsTranslator,), attrs)


def compile_ok(src: str, regalloc: str = "stack"):
    res = compile_source(src, regalloc=regalloc)
    assert res.ok, [str(e) for e in res.errors]
    return res


def translate(src: str, regalloc: str = "stack"):
    """(CompileResult, MipsProgram) usando el traductor de pruebas."""
    res = compile_ok(src, regalloc)
    return res, translator_class()(res.program, res.table, regalloc).translate()


def run_source(src: str, regalloc: str = "stack", registers: Sequence[str] = ()):
    """Compila, ejecuta en MARS y devuelve (MarsRun, salida del intérprete de TAC)."""
    res, prog = translate(src, regalloc)
    return run_asm(prog.text(), registers=registers), interp_run(res.program, res.table)
