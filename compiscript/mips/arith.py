"""Aritmética entera y float, copias, negación y `int_to_float`.

| TAC                  | integer                               | float                     |
|----------------------|---------------------------------------|---------------------------|
| `t = a + b`          | `addu t, a, b`                        | `add.s t, a, b`           |
| `t = a - b`          | `subu t, a, b`                        | `sub.s t, a, b`           |
| `t = a * b`          | `mul t, a, b`                         | `mul.s t, a, b`           |
| `t = a / b`          | revisión de cero + `div a, b`/`mflo t`| revisión de cero + `div.s`|
| `t = a % b`          | revisión de cero + `div a, b`/`mfhi t`| `a - b·trunc(a / b)`      |
| `t = minus a`        | `subu t, $zero, a`                    | `neg.s t, a`              |
| `t = not a`          | `xori t, a, 1`                        |                           |
| `x = y`              | `move` (o `lw`/`sw` si vive en memoria)| `mov.s`                  |
| `t = int_to_float a` | `mtc1 a, t` + `cvt.s.w t, t`          |                           |

`div` de MIPS trunca hacia cero y el residuo toma el signo del dividendo, igual
que el intérprete de TAC (`7 / -2 == -3`, `7 % -2 == 1`). Antes de `/` y `%` se
revisa el divisor según `runtime.checks_for(op)`: si es cero se salta a
`__raise` con el mensaje `division_by_zero`.

Registros auxiliares fuera de `RegisterManager` (nunca guardan un temporal
entre instrucciones): `$v1` para revisar el divisor float y `$f2` para el
cociente de `%` float.
"""

from __future__ import annotations

from typing import Optional

from ..ir.runtime import RuntimeErrorKind, checks_for
from ..ir.tac import Const, Op, Operand, Quad
from ..types import BOOLEAN, FLOAT, STRING

INT_TMP = "$v1"
FLOAT_TMP = "$f2"

INT_OPS = {Op.ADD: "addu", Op.SUB: "subu", Op.MUL: "mul"}
FLOAT_OPS = {Op.ADD: "add.s", Op.SUB: "sub.s", Op.MUL: "mul.s", Op.DIV: "div.s"}


# --------------------------------------------------------------- tipos

def type_of(x: Optional[Operand]):
    if isinstance(x, Const):
        v = x.value
        if isinstance(v, bool):
            return BOOLEAN
        if isinstance(v, float):
            return FLOAT
        if isinstance(v, str):
            return STRING
        return None
    return getattr(x, "type", None)


def is_float(*xs: Optional[Operand]) -> bool:
    return any(x is not None and x.is_float for x in xs)


def is_bool(x: Optional[Operand]) -> bool:
    return type_of(x) == BOOLEAN


def is_string(x: Optional[Operand]) -> bool:
    return type_of(x) == STRING


class ArithMixin:
    """Handlers de `+ - * / %`, `minus`, `not`, `=` e `int_to_float`."""

    # ---------------------------------------------------------- utilidades

    def guard(self, branch: str, reg: str, kind: str) -> None:
        """`branch reg, ok` y, si no salta, error en ejecución `kind`.
        Ej.: `guard("bnez", divisor, "division_by_zero")`."""
        ok = self.new_label("ok")
        self.asm.emit(branch, reg, ok)
        self.runtime_error(kind)
        self.asm.label(ok)

    def check_divisor(self, op: str, b: str, floating: bool) -> None:
        if RuntimeErrorKind.DIVISION_BY_ZERO not in checks_for(op):
            return
        if floating:
            # +0.0 y -0.0 solo difieren en el bit de signo: se descarta
            self.asm.emit("mfc1", INT_TMP, b, comment="bits del divisor")
            self.asm.emit("sll", INT_TMP, INT_TMP, 1, comment="sin el signo")
            b = INT_TMP
        self.guard("bnez", b, RuntimeErrorKind.DIVISION_BY_ZERO)

    def binary_operands(self, q: Quad, pos: int):
        return self.regs.load(q.arg1, pos), self.regs.load(q.arg2, pos)

    def finish(self, d: str, q: Quad, pos: int) -> None:
        self.regs.store(d, q.result, pos)

    # ----------------------------------------------------------- + - * / %

    def arith(self, q: Quad, pos: int) -> None:
        op = q.op
        floating = is_float(q.arg1, q.arg2, q.result)
        a, b = self.binary_operands(q, pos)
        if op in (Op.DIV, Op.MOD):
            self.check_divisor(op, b, floating)
        d = self.regs.dest(q.result, pos)
        if floating:
            if op == Op.MOD:            # a - b * trunc(a / b), como el intérprete
                self.asm.emit("div.s", FLOAT_TMP, a, b)
                self.asm.emit("trunc.w.s", FLOAT_TMP, FLOAT_TMP)
                self.asm.emit("cvt.s.w", FLOAT_TMP, FLOAT_TMP)
                self.asm.emit("mul.s", FLOAT_TMP, FLOAT_TMP, b)
                self.asm.emit("sub.s", d, a, FLOAT_TMP)
            else:
                self.asm.emit(FLOAT_OPS[op], d, a, b)
        elif op in (Op.DIV, Op.MOD):
            self.asm.emit("div", a, b)
            self.asm.emit("mflo" if op == Op.DIV else "mfhi", d)
        else:
            self.asm.emit(INT_OPS[op], d, a, b)
        self.finish(d, q, pos)

    op_add = op_sub = op_mul = op_div = op_mod = arith

    # ------------------------------------------------------------- unarias

    def op_neg(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.arg1, pos)
        d = self.regs.dest(q.result, pos)
        if is_float(q.arg1, q.result):
            self.asm.emit("neg.s", d, a)
        else:
            self.asm.emit("subu", d, "$zero", a)
        self.finish(d, q, pos)

    def op_not(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.arg1, pos)
        d = self.regs.dest(q.result, pos)
        self.asm.emit("xori", d, a, 1)
        self.finish(d, q, pos)

    def op_int_to_float(self, q: Quad, pos: int) -> None:
        a = self.regs.load(q.arg1, pos)
        d = self.regs.dest(q.result, pos)
        self.asm.emit("mtc1", a, d)
        self.asm.emit("cvt.s.w", d, d)
        self.finish(d, q, pos)

    # --------------------------------------------------------------- copia

    def op_assign(self, q: Quad, pos: int) -> None:
        src = self.regs.load(q.arg1, pos)
        if q.result.is_float and not src.startswith("$f"):
            # integer -> float sin int_to_float (no debería ocurrir): convertir
            d = self.regs.dest(q.result, pos)
            self.asm.emit("mtc1", src, d)
            self.asm.emit("cvt.s.w", d, d)
            src = d
        self.regs.store(src, q.result, pos)


__all__ = ["ArithMixin", "FLOAT_TMP", "INT_TMP", "is_bool", "is_float", "is_string", "type_of"]
