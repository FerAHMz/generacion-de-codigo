"""Arreglos: `alloc`, `len`, `t = a[i]` y `a[i] = x`.

Un arreglo de `n` elementos ocupa `4 + 4n` bytes en el heap (`sbrk`, syscall 9):

    [base + 0]        n (longitud)
    [base + 4 + 4·i]  elemento i (una palabra; float con l.s/s.s)

| TAC          | MIPS                                                                 |
|--------------|----------------------------------------------------------------------|
| `t = alloc n`| `sll $a0, n, 2` · `addiu $a0, $a0, 4` · syscall 9 · `sw n, 0($v0)`   |
| `t = len a`  | revisión de null · `lw t, 0(a)`                                      |
| `t = a[i]`   | revisión de null · `lw $v1, 0(a)` · `sltu $v1, i, $v1` (0 ≤ i < len  |
|              | en una sola comparación sin signo) · `sll`/`addu` · `lw t, 4($v1)`   |
| `a[i] = x`   | igual, terminando en `sw x, 4($v1)`                                  |

Las revisiones salen de `runtime.checks_for(op)`; si fallan se salta a
`__raise` con el mensaje (`null_reference`, `index_out_of_bounds`).
`$v1` se usa como registro auxiliar después de cargar los operandos.
"""

from __future__ import annotations

from ..ir.runtime import RuntimeErrorKind, checks_for
from ..ir.tac import Const, Op, Quad
from .arith import INT_TMP, is_float

WORD = 4


class DataStructsMixin:
    """Handlers de `alloc`, `len`, `[]` y `[]=`."""

    def check_not_null(self, op: str, ref: str) -> None:
        if RuntimeErrorKind.NULL_REFERENCE in checks_for(op):
            self.guard("bnez", ref, RuntimeErrorKind.NULL_REFERENCE)

    def element_address(self, op: str, array: str, index: str) -> str:
        """Revisa null e índice y deja en $v1 la dirección `array + 4·index`
        (el elemento está en `4($v1)`)."""
        self.check_not_null(op, array)
        if RuntimeErrorKind.INDEX_OUT_OF_BOUNDS in checks_for(op):
            self.asm.emit("lw", INT_TMP, f"0({array})", comment="longitud")
            self.asm.emit("sltu", INT_TMP, index, INT_TMP, comment="0 <= i < len")
            self.guard("bnez", INT_TMP, RuntimeErrorKind.INDEX_OUT_OF_BOUNDS)
        self.asm.emit("sll", INT_TMP, index, 2)
        self.asm.emit("addu", INT_TMP, array, INT_TMP)
        return INT_TMP

    # ----------------------------------------------------------------- alloc

    def op_alloc(self, q: Quad, pos: int) -> None:
        n = q.arg1
        if isinstance(n, Const):
            count = int(n.value)
            self.asm.emit("li", "$a0", WORD + WORD * count, comment=f"{count} elementos + longitud")
            self.asm.emit("li", "$v0", 9)
            self.asm.emit("syscall", comment="sbrk")
            self.asm.emit("li", INT_TMP, count)
            self.asm.emit("sw", INT_TMP, "0($v0)", comment="longitud")
        else:
            r = self.regs.load(n, pos)
            self.asm.emit("sll", "$a0", r, 2)
            self.asm.emit("addiu", "$a0", "$a0", WORD, comment="elementos + longitud")
            self.asm.emit("li", "$v0", 9)
            self.asm.emit("syscall", comment="sbrk")
            self.asm.emit("sw", r, "0($v0)", comment="longitud")
        self.regs.store("$v0", q.result, pos)

    # ------------------------------------------------------------------- len

    def op_len(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.arg1, pos)
        self.check_not_null(q.op, a)
        d = self.regs.dest(q.result, pos)
        self.asm.emit("lw", d, f"0({a})", comment="longitud")
        self.regs.store(d, q.result, pos)

    # --------------------------------------------------------------- a[i]

    def op_index_get(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.arg1, pos)
        i = self.regs.load(q.arg2, pos)
        addr = self.element_address(q.op, a, i)
        d = self.regs.dest(q.result, pos)
        self.asm.emit("l.s" if is_float(q.result) else "lw", d, f"{WORD}({addr})")
        self.regs.store(d, q.result, pos)

    def op_index_set(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.result, pos)
        i = self.regs.load(q.arg1, pos)
        x = self.regs.load(q.arg2, pos)
        addr = self.element_address(q.op, a, i)
        self.asm.emit("s.s" if x.startswith("$f") else "sw", x, f"{WORD}({addr})")


__all__ = ["DataStructsMixin"]
