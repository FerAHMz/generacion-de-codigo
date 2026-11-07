"""Generación de código intermedio (segunda pasada del compilador).

    from compiscript.codegen import compile_source
    result = compile_source(src)
    result.errors     # errores sintácticos/semánticos (si hay, no hay TAC)
    result.program    # TACProgram o None
    result.to_dict()  # {"errors", "tac", "symbols", "mips"} — contrato de /api/compile
    result.asm        # programa MIPS como texto (None si hubo errores)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..errors import CompilerError, ErrorCollector
from ..ir.tac import TACProgram
from ..semantic import AnalysisResult, analyze
from .base import CodeGenBase, CodegenError, JumpTargets
from .generator import TACGenerator


@dataclass
class CompileResult:
    analysis: AnalysisResult
    program: Optional[TACProgram]
    regalloc: str = "stack"
    _mips: Optional[object] = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.analysis.ok and self.program is not None

    @property
    def errors(self) -> List[CompilerError]:
        return list(self.analysis.errors)

    @property
    def table(self):
        return self.analysis.table

    def tac_lines(self) -> List[str]:
        return self.program.lines() if self.program is not None else []

    @property
    def mips(self):
        """`MipsProgram` del programa (se genera la primera vez que se pide).
        None si hubo errores; lanza `MipsNotImplemented` si alguna instrucción
        todavía no tiene traducción."""
        if self.program is None:
            return None
        if self._mips is None:
            from ..mips import generate_mips
            self._mips = generate_mips(self.program, self.table, self.regalloc)
        return self._mips

    @property
    def asm(self) -> Optional[str]:
        """Texto del .asm listo para MARS (None si hubo errores)."""
        prog = self.mips
        return prog.text() if prog is not None else None

    def mips_lines(self) -> List[str]:
        from ..mips import MipsNotImplemented
        try:
            text = self.asm
        except MipsNotImplemented:
            return []
        return text.splitlines() if text else []

    def to_dict(self) -> dict:
        return {
            "errors": [{"phase": e.phase, "line": e.line, "column": e.column, "message": e.message}
                       for e in self.errors],
            "tac": self.tac_lines(),
            "symbols": self.table.to_dict(),
            "mips": self.mips_lines(),
        }


def compile_source(source: str, errors: Optional[ErrorCollector] = None,
                   regalloc: str = "stack") -> CompileResult:
    """Pasada 1 (análisis semántico) y, solo si no hubo errores, pasada 2 (TAC).
    El MIPS se genera a pedido (`result.asm`) con el modo de registros `regalloc`."""
    analysis = analyze(source, errors)
    if not analysis.ok:
        return CompileResult(analysis, None, regalloc)
    return CompileResult(analysis, TACGenerator(analysis).generate(), regalloc)


def compile_file(path: str, errors: Optional[ErrorCollector] = None,
                 regalloc: str = "stack") -> CompileResult:
    with open(path, encoding="utf-8") as fh:
        return compile_source(fh.read(), errors, regalloc)


__all__ = ["CodeGenBase", "CodegenError", "CompileResult", "JumpTargets", "TACGenerator",
           "compile_file", "compile_source"]
