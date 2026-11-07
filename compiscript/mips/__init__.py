"""Generación de código MIPS32 a partir del TAC (tercera fase del compilador).

    from compiscript.codegen import compile_source
    res = compile_source(src, regalloc="stack")
    res.asm            # texto del .asm (None si hubo errores)

    from compiscript.mips import generate_mips
    asm = generate_mips(res.program, res.table)    # MipsProgram

Módulos:
  asm.py         programa MIPS (.data, .text, rutinas del runtime)
  translator.py  recorrido del TAC y despacho por instrucción
  regs.py        getReg(): registros de cada temporal (modo pila / linear scan)
  calls.py       marcos, prólogo/epílogo y secuencias de llamada
"""

from .asm import MipsProgram
from .regs import MODES, RegisterManager
from .translator import MipsNotImplemented, MipsTranslator, generate_mips

__all__ = ["MODES", "MipsNotImplemented", "MipsProgram", "MipsTranslator", "RegisterManager",
           "generate_mips"]
