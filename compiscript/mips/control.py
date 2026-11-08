"""Relacionales, saltos, etiquetas y `print`.

Relacionales con valor (`t = a < b`):

| TAC      | integer / referencias | float                                  |
|----------|-----------------------|----------------------------------------|
| `a < b`  | `slt t, a, b`         | `c.lt.s a, b`                          |
| `a <= b` | `sle t, a, b`         | `c.le.s a, b`                          |
| `a > b`  | `sgt t, a, b`         | `c.lt.s b, a`                          |
| `a >= b` | `sge t, a, b`         | `c.le.s b, a`                          |
| `a == b` | `seq t, a, b`         | `c.eq.s a, b`                          |
| `a != b` | `sne t, a, b`         | `c.eq.s a, b` con el resultado negado  |

En float la comparación deja la bandera del coprocesador 1 y el valor se
materializa con `li t, 1` + `bc1t`/`bc1f` + `li t, 0`. Los saltos `if a relop
b goto L` usan `blt`/`ble`/`bgt`/`bge`/`beq`/`bne` (o `c.xx.s` + `bc1t`/`bc1f`).

`==`/`!=` entre strings compara el contenido (como el intérprete), con un
recorrido byte a byte en línea; entre referencias (arreglos, objetos, null)
compara direcciones.

`print x` usa las syscalls de MARS: 1 (integer), 2 (float), 4 (string;
`null` si la dirección es 0) y para boolean imprime `true`/`false`; después
la syscall 11 con `'\\n'`.
"""

from __future__ import annotations

from ..ir.tac import Const, Op, Quad
from ..types import BOOLEAN, FLOAT, INTEGER, NULL, STRING
from .arith import INT_TMP, is_float, is_string, type_of

INT_SET = {Op.LT: "slt", Op.LE: "sle", Op.GT: "sgt", Op.GE: "sge", Op.EQ: "seq", Op.NE: "sne"}
INT_BRANCH = {Op.LT: "blt", Op.LE: "ble", Op.GT: "bgt", Op.GE: "bge", Op.EQ: "beq", Op.NE: "bne"}
# relop -> (comparación de c1, intercambiar operandos, verdadero cuando la bandera es 1)
FLOAT_CMP = {
    Op.LT: ("c.lt.s", False, True), Op.LE: ("c.le.s", False, True),
    Op.GT: ("c.lt.s", True, True), Op.GE: ("c.le.s", True, True),
    Op.EQ: ("c.eq.s", False, True), Op.NE: ("c.eq.s", False, False),
}


def unsupported(message: str) -> None:
    from .translator import MipsNotImplemented   # import diferido: translator importa este módulo
    raise MipsNotImplemented(message)


class ControlMixin:
    """Handlers de relacionales, `goto`, `if`, `ifFalse`, `if<`…, `label` y `print`."""

    # ---------------------------------------------------- comparación float

    def float_compare(self, relop: str, a: str, b: str) -> str:
        """Emite `c.xx.s` y devuelve la rama que salta cuando `a relop b`."""
        cmp, swap, when_true = FLOAT_CMP[relop]
        self.asm.emit(cmp, *((b, a) if swap else (a, b)))
        return "bc1t" if when_true else "bc1f"

    def string_equal(self, a: str, b: str, equal: str, different: str) -> None:
        """Salta a `equal` si los strings `a` y `b` tienen el mismo contenido
        (o son la misma dirección, incluido null == null); si no, a `different`.
        Usa $a0, $a1, $v0 y $v1, que no guardan temporales."""
        loop = self.new_label("streq")
        self.asm.emit("beq", a, b, equal, comment="misma dirección")
        self.asm.emit("beqz", a, different, comment="null")
        self.asm.emit("beqz", b, different)
        self.asm.emit("move", "$a0", a)
        self.asm.emit("move", "$a1", b)
        self.asm.label(loop)
        self.asm.emit("lb", "$v0", "0($a0)")
        self.asm.emit("lb", INT_TMP, "0($a1)")
        self.asm.emit("bne", "$v0", INT_TMP, different)
        self.asm.emit("beqz", "$v0", equal, comment="fin de los dos strings")
        self.asm.emit("addiu", "$a0", "$a0", 1)
        self.asm.emit("addiu", "$a1", "$a1", 1)
        self.asm.emit("j", loop)

    def compares_strings(self, relop: str, q: Quad) -> bool:
        return relop in (Op.EQ, Op.NE) and is_string(q.arg1) and is_string(q.arg2)

    # ---------------------------------------------- relacionales con valor

    def relational(self, q: Quad, pos: int) -> None:
        relop = q.op
        a = self.regs.load(q.arg1, pos)
        b = self.regs.load(q.arg2, pos)
        d = self.regs.dest(q.result, pos)
        if self.compares_strings(relop, q):
            yes, no, end = self.new_label("eq"), self.new_label("ne"), self.new_label("cmp")
            self.string_equal(a, b, yes if relop == Op.EQ else no, no if relop == Op.EQ else yes)
            self.asm.label(yes)
            self.asm.emit("li", d, 1)
            self.asm.emit("j", end)
            self.asm.label(no)
            self.asm.emit("li", d, 0)
            self.asm.label(end)
        elif is_float(q.arg1, q.arg2):
            done = self.new_label("cmp")
            branch = self.float_compare(relop, a, b)
            self.asm.emit("li", d, 1)
            self.asm.emit(branch, done)
            self.asm.emit("li", d, 0)
            self.asm.label(done)
        else:
            self.asm.emit(INT_SET[relop], d, a, b)
        self.regs.store(d, q.result, pos)

    op_lt = op_le = op_gt = op_ge = op_eq = op_ne = relational

    # ---------------------------------------------------------------- saltos

    def op_label(self, q: Quad, pos: int) -> None:
        self.asm.label(q.result.name)

    def op_goto(self, q: Quad, pos: int) -> None:
        self.asm.emit("j", q.result.name)

    def op_if(self, q: Quad, pos: int) -> None:
        self.asm.emit("bnez", self.regs.load(q.arg1, pos), q.result.name)

    def op_if_false(self, q: Quad, pos: int) -> None:
        self.asm.emit("beqz", self.regs.load(q.arg1, pos), q.result.name)

    def conditional_jump(self, q: Quad, pos: int) -> None:
        relop = Op.relop_of(q.op)
        target = q.result.name
        a = self.regs.load(q.arg1, pos)
        b = self.regs.load(q.arg2, pos)
        if self.compares_strings(relop, q):
            skip = self.new_label("cmp")
            self.string_equal(a, b, target if relop == Op.EQ else skip,
                              skip if relop == Op.EQ else target)
            self.asm.label(skip)
        elif is_float(q.arg1, q.arg2):
            self.asm.emit(self.float_compare(relop, a, b), target)
        else:
            self.asm.emit(INT_BRANCH[relop], a, b, target)

    op_if_lt = op_if_le = op_if_gt = op_if_ge = op_if_eq = op_if_ne = conditional_jump

    # ----------------------------------------------------------------- print

    def syscall(self, code: int) -> None:
        self.asm.emit("li", "$v0", code)
        self.asm.emit("syscall")

    def op_print(self, q: Quad, pos: int) -> None:
        x = q.arg1
        typ = type_of(x)
        if isinstance(x, Const) and x.value is None or typ == NULL:
            self.asm.emit("la", "$a0", self.asm.string("null"))
            self.syscall(4)
        elif typ == BOOLEAN:
            r = self.regs.load(x, pos)
            skip = self.new_label("pb")
            self.asm.emit("la", "$a0", self.asm.string("true"))
            self.asm.emit("bnez", r, skip)
            self.asm.emit("la", "$a0", self.asm.string("false"))
            self.asm.label(skip)
            self.syscall(4)
        elif typ == FLOAT:
            self.asm.emit("mov.s", "$f12", self.regs.load(x, pos))
            self.syscall(2)
        elif typ == STRING:
            r = self.regs.load(x, pos)
            skip = self.new_label("ps")
            self.asm.emit("move", "$a0", r)
            self.asm.emit("bnez", r, skip)
            self.asm.emit("la", "$a0", self.asm.string("null"))
            self.asm.label(skip)
            self.syscall(4)
        elif typ == INTEGER or typ is None and isinstance(x, Const):
            self.asm.emit("move", "$a0", self.regs.load(x, pos))
            self.syscall(1)
        else:
            unsupported(f"print de un valor de tipo {typ} (conversión a texto): {q.text()}")
        self.asm.emit("li", "$a0", 10, comment="'\\n'")
        self.syscall(11)


__all__ = ["ControlMixin"]
