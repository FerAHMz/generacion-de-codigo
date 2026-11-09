"""Objetos: vtables, `new`, atributos y despacho dinámico.

Cada clase tiene su vtable en `.data`, en el orden de `ClassLayout.vtable`
(un método sobreescrito ocupa la misma ranura que en el padre):

    __vtable_Perro: .word Perro_hablar, Animal_comer

| TAC                 | MIPS                                                              |
|---------------------|-------------------------------------------------------------------|
| `t = new C, size`   | `li $a0, size` · syscall 9 · `la $v1, __vtable_C` · `sw $v1, 0($v0)` |
| `t = [obj + off]`   | revisión de null · `lw`/`lb`/`l.s t, off(obj)`                    |
| `[obj + off] = x`   | revisión de null · `sw`/`sb`/`s.s x, off(obj)`                    |
| `t = method obj, m` | revisión de null · `lw $v1, 0(obj)` · `lw t, 4·slot($v1)`         |

La dirección que deja `method` la usa el `call t, n` siguiente con `jalr`
(`calls.py`). Un atributo boolean ocupa 1 byte (`lb`/`sb`).
"""

from __future__ import annotations

from typing import Optional

from ..ir.tac import Const, Field, Label, Operand, Quad
from ..symbols import ClassLayout
from ..types import ClassType
from .arith import INT_TMP, is_bool, is_float


def vtable_label(class_name: str) -> str:
    return f"__vtable_{class_name}"


class ObjectsMixin:
    """Vtables (`setup_vtables`) y handlers de `new`, `getf`, `setf` y `method`."""

    # ---------------------------------------------------------------- .data

    def setup_vtables(self) -> None:
        for name, layout in self.table.class_layouts.items():
            labels = [label for _, label in layout.vtable] or ["0"]
            self.asm.data(vtable_label(name), ".word", *labels,
                          comment=f"vtable de {name} ({len(layout.vtable)} métodos)")

    # ----------------------------------------------------------- utilidades

    def layout_named(self, label: Operand) -> ClassLayout:
        """Layout de la clase de `new C`: la etiqueta coincide con el nombre salvo
        que choque con otra (`C_2`), como en el intérprete."""
        name = label.name if isinstance(label, Label) else str(label)
        layouts = self.table.class_layouts
        if name not in layouts and name.rsplit("_", 1)[0] in layouts:
            name = name.rsplit("_", 1)[0]
        if name not in layouts:
            raise ValueError(f"clase desconocida en new: {name}")
        return layouts[name]

    def static_layout(self, obj: Operand) -> Optional[ClassLayout]:
        cls = getattr(obj, "type", None)
        return self.table.class_layouts.get(cls.name) if isinstance(cls, ClassType) else None

    def field_is_byte(self, obj: Operand, f: Field, value: Optional[Operand]) -> bool:
        layout = self.static_layout(obj)
        if layout is not None:
            for _, off, size, _ in layout.fields:
                if off == f.offset:
                    return size == 1
        return is_bool(value)

    # ------------------------------------------------------------------ new

    def op_new(self, q: Quad, pos: int) -> None:
        layout = self.layout_named(q.arg1)
        size = q.arg2.value if isinstance(q.arg2, Const) else layout.object_size
        self.asm.emit("li", "$a0", int(size), comment=f"new {layout.name}")
        self.asm.emit("li", "$v0", 9)
        self.asm.emit("syscall", comment="sbrk")
        self.asm.emit("la", INT_TMP, vtable_label(layout.name))
        self.asm.emit("sw", INT_TMP, "0($v0)", comment="vtable")
        self.regs.store("$v0", q.result, pos)

    # ------------------------------------------------------------ atributos

    def op_getf(self, q: Quad, pos: int) -> None:
        obj = self.regs.load(q.arg1, pos)
        self.check_not_null(q.op, obj)
        d = self.regs.dest(q.result, pos)
        f = q.arg2
        if is_float(q.result):
            op = "l.s"
        else:
            op = "lb" if self.field_is_byte(q.arg1, f, q.result) else "lw"
        self.asm.emit(op, d, f"{f.offset}({obj})", comment=f.name)
        self.regs.store(d, q.result, pos)

    def op_setf(self, q: Quad, pos: int) -> None:
        obj = self.regs.load(q.result, pos)
        x = self.regs.load(q.arg2, pos)
        self.check_not_null(q.op, obj)
        f = q.arg1
        if x.startswith("$f"):
            op = "s.s"
        else:
            op = "sb" if self.field_is_byte(q.result, f, q.arg2) else "sw"
        self.asm.emit(op, x, f"{f.offset}({obj})", comment=f.name)

    # --------------------------------------------------------------- method

    def method_slot_of(self, obj: Operand, name: str) -> int:
        layout = self.static_layout(obj)
        slot = layout.method_slot(name) if layout else None
        if slot is None:      # tipo estático desconocido: cualquier clase con ese método
            slots = {l.method_slot(name) for l in self.table.class_layouts.values()} - {None}
            if len(slots) != 1:
                raise ValueError(f"no se puede resolver la ranura del método {name}")
            slot = slots.pop()
        return slot

    def op_method(self, q: Quad, pos: int) -> None:
        name = q.arg2.name if isinstance(q.arg2, Label) else str(q.arg2)
        slot = self.method_slot_of(q.arg1, name)
        obj = self.regs.load(q.arg1, pos)
        self.check_not_null(q.op, obj)
        self.asm.emit("lw", INT_TMP, f"0({obj})", comment="vtable")
        d = self.regs.dest(q.result, pos)
        self.asm.emit("lw", d, f"{4 * slot}({INT_TMP})", comment=f"ranura {slot}: {name}")
        self.regs.store(d, q.result, pos)


__all__ = ["ObjectsMixin", "vtable_label"]
