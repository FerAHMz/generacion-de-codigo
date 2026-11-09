"""Traductor de TAC a MIPS32: recorre los cuádruplos y despacha cada uno a su
handler.

Cada instrucción TAC `op` se traduce en un método `op_<nombre>(q, pos)` (ver
`OP_NAMES`), donde `q` es el cuádruplo y `pos` su índice en el programa (la
asignación de registros se consulta por posición). Los handlers viven en
mixins, uno por grupo de instrucciones; para agregar un grupo basta con
heredar del mixin en `MipsTranslator`. Una instrucción sin handler lanza
`MipsNotImplemented` (los tests de extremo a extremo la marcan como skip).

Los mixins pueden definir métodos `setup_<algo>()` (se llaman antes de
traducir, en orden alfabético) para preparar el segmento de datos, p. ej.
las variables globales o las vtables.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from ..ir.liveness import function_ranges
from ..ir.runtime import MESSAGES
from ..ir.tac import Op, Quad, TACProgram
from ..symbols import ActivationRecord, SymbolTable
from .asm import MipsProgram
from .arith import ArithMixin
from .calls import CallsMixin
from .control import ControlMixin
from .data_structs import DataStructsMixin
from .memory import MemoryMixin
from .objects import ObjectsMixin
from .regs import RegisterManager

# Nombre del handler de cada instrucción TAC: op_<nombre>.
OP_NAMES: Dict[str, str] = {
    Op.ADD: "add", Op.SUB: "sub", Op.MUL: "mul", Op.DIV: "div", Op.MOD: "mod",
    Op.LT: "lt", Op.LE: "le", Op.GT: "gt", Op.GE: "ge", Op.EQ: "eq", Op.NE: "ne",
    Op.NEG: "neg", Op.NOT: "not", Op.ASSIGN: "assign",
    Op.LABEL: "label", Op.GOTO: "goto", Op.IF: "if", Op.IF_FALSE: "if_false",
    Op.FUNC_BEGIN: "func_begin", Op.FUNC_END: "func_end", Op.PARAM: "param",
    Op.CALL: "call", Op.RETURN: "return",
    Op.INDEX_GET: "index_get", Op.INDEX_SET: "index_set", Op.LEN: "len", Op.ALLOC: "alloc",
    Op.NEW: "new", Op.FIELD_GET: "getf", Op.FIELD_SET: "setf", Op.METHOD: "method",
    Op.PRINT: "print", Op.CONCAT: "concat", Op.INT_TO_FLOAT: "int_to_float",
    Op.PUSH_HANDLER: "push_handler", Op.POP_HANDLER: "pop_handler",
    Op.GET_EXCEPTION: "get_exception",
}
_RELOP_NAMES = {Op.LT: "lt", Op.LE: "le", Op.GT: "gt", Op.GE: "ge", Op.EQ: "eq", Op.NE: "ne"}

ERROR_PREFIX = "Error en tiempo de ejecución: "


def handler_name(op: str) -> str:
    """`op_add` para `+`, `op_if_lt` para `if<`, ..."""
    relop = Op.relop_of(op)
    if relop is not None:
        return "op_if_" + _RELOP_NAMES[relop]
    name = OP_NAMES.get(op)
    if name is None:
        raise MipsNotImplemented(f"instrucción TAC desconocida: {op}")
    return "op_" + name


class MipsNotImplemented(NotImplementedError):
    """Instrucción TAC que todavía no tiene traducción a MIPS."""


# Rutina __raise provisional: imprime el mensaje de $a0 y termina con código 1.
# La reemplaza la versión con pila de manejadores (try/catch).
RAISE_PROVISIONAL = """
__raise:                                # $a0 = mensaje del error
        move $t8, $a0
        la $a0, __err_prefix
        li $v0, 4
        syscall
        move $a0, $t8
        li $v0, 4
        syscall
        li $a0, 10
        li $v0, 11
        syscall
        li $a0, 1
        li $v0, 17                      # exit2: termina con código 1
        syscall
"""


class MipsTranslator(MemoryMixin, CallsMixin, ArithMixin, ControlMixin, DataStructsMixin,
                     ObjectsMixin):
    # Instrucciones que llaman con `jal` a una rutina del runtime: una función
    # que las use guarda $ra aunque no llame a otras funciones de Compiscript.
    RUNTIME_CALL_OPS = {Op.CONCAT, Op.PRINT, Op.ALLOC, Op.NEW}

    def __init__(self, program: TACProgram, table: SymbolTable, regalloc: str = "linear"):
        self.program = program
        self.table = table
        self.asm = MipsProgram()
        self.regs = RegisterManager(self, program, table, regalloc)
        self.functions: Dict[str, Tuple[int, int]] = {
            name: (lo, hi) for name, lo, hi in function_ranges(program)}
        self.function: Optional[str] = None
        self.record: Optional[ActivationRecord] = None

    # ------------------------------------------------------------ recorrido

    def translate(self) -> MipsProgram:
        for name in sorted(n for n in dir(self) if n.startswith("setup_")):
            getattr(self, name)()
        for pos, q in enumerate(self.program):
            self.translate_quad(q, pos)
        return self.asm

    def translate_quad(self, q: Quad, pos: int) -> None:
        self.regs.begin(pos)
        if q.op not in (Op.LABEL, Op.FUNC_BEGIN, Op.FUNC_END):
            self.asm.comment(q.text())
        handler = getattr(self, handler_name(q.op), None)
        if handler is None:
            raise MipsNotImplemented(f"instrucción TAC sin traducción a MIPS: {q.text()}")
        handler(q, pos)

    def record_of(self, label: str) -> Optional[ActivationRecord]:
        return self.table.record_of(label)

    def function_quads(self, label: Optional[str] = None):
        lo, hi = self.functions[label or self.function]
        return self.program.quads[lo:hi + 1]

    # ------------------------------------------------------------ utilidades

    def new_label(self, hint: str = "L") -> str:
        """Etiqueta interna única (no choca con las del TAC)."""
        return self.asm.unique(f"__{hint}")

    def error_message(self, kind: str) -> str:
        """Etiqueta del mensaje de un error en tiempo de ejecución (`runtime.MESSAGES`)."""
        return self.asm.data(f"__err_{kind}", ".asciiz", f'"{MESSAGES[kind]}"')

    def runtime_error(self, kind: str) -> None:
        """Salta a `__raise` con el mensaje del error en $a0 (no regresa)."""
        self.asm.emit("la", "$a0", self.error_message(kind))
        self.asm.emit("j", "__raise", comment=MESSAGES[kind])
        self.require_raise()

    def require_raise(self) -> None:
        if not self.asm.has_routine("__raise"):
            self.asm.data("__err_prefix", ".asciiz", f'"{ERROR_PREFIX}"')
            self.asm.add_routine("__raise", RAISE_PROVISIONAL)


def generate_mips(program: TACProgram, table: SymbolTable, regalloc: str = "linear") -> MipsProgram:
    """Traduce un programa TAC (con su tabla de símbolos ya con direcciones) a MIPS."""
    return MipsTranslator(program, table, regalloc).translate()


__all__ = ["MipsNotImplemented", "MipsTranslator", "OP_NAMES", "generate_mips", "handler_name"]
