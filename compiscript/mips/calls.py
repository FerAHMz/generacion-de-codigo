"""Marcos de pila, prólogo/epílogo y secuencias de llamada y retorno.

Marco de una función (la pila crece hacia direcciones bajas):

            ...                    marco del llamador
    fp + .. parámetros             los guarda el llamador (el 0 junto al encabezado)
    fp + .. [static link]          lo apila el llamador, solo si el llamado lo usa
    fp + 4  [dirección de retorno] la guarda el prólogo si la función no es hoja
    fp + 0  control link           $fp del llamador
    fp - .. locales                ActivationRecord.locals
    fp - .. ranuras de spill       temporales que no están en un registro
    fp - .. [$ra extra]            función hoja que llama a una rutina del runtime
    fp - .. registros $s           los que usa la función (callee-saved)
            <- $sp

`main` no tiene encabezado: `$fp = $sp` al empezar y termina con la syscall 10.

Secuencia de llamada para `param a1 ... param an` + `t = call f, n`
(los `param` de una llamada siempre van juntos, justo antes del `call`):

  1. en el primer `param`: guardar los registros $t/$f con valores vivos
     después de la llamada (`RegisterManager.live_across`) y reservar el área
     de argumentos (4·n bytes, o lo que ocupen según su tipo);
  2. cada `param i`: `sw`/`s.s`/`sb` en su offset (el parámetro 0 en la
     dirección más baja, para que quede en `fp[+encabezado + off]` del llamado);
  3. en el `call`: apilar el static link si el llamado lo usa (siguiendo
     p - q + 1 enlaces desde el marco actual), `jal f` (o `jalr` con la
     dirección que dejó `method`), liberar argumentos y static link,
     restaurar los registros guardados y copiar el resultado de $v0 / $f0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..ir.tac import Const, Label, Op, Operand, Quad, Temp
from ..symbols import WORD, ActivationRecord, align, sizeof
from ..types import ClassType


@dataclass
class FrameLayout:
    """Parte del marco que reserva el prólogo (debajo de $fp)."""

    label: str
    record: ActivationRecord
    spill_words: int = 0
    extra_ra: bool = False
    saved_s: List[str] = field(default_factory=list)

    @property
    def spill_base(self) -> int:
        return self.record.temps_base

    @property
    def ra_offset(self) -> int:
        """Offset de $ra respecto a $fp (en el encabezado o en la ranura extra)."""
        header = self.record.header_offset("return_address")
        if header is not None:
            return header
        return -(self.spill_base + WORD * (self.spill_words + 1))

    @property
    def saves_ra(self) -> bool:
        return self.record.needs_return_address or self.extra_ra

    def s_offset(self, i: int) -> int:
        return -(self.spill_base + WORD * (self.spill_words + int(self.extra_ra) + i + 1))

    @property
    def reserve(self) -> int:
        """Bytes que el prólogo resta a $sp después de fijar $fp."""
        return self.spill_base + WORD * (self.spill_words + int(self.extra_ra) + len(self.saved_s))


@dataclass
class PendingCall:
    """Estado de una llamada entre su primer `param` y su `call`."""

    call_pos: int
    callee: Optional[ActivationRecord]
    saved: List[str]
    area: int
    slots: List[Tuple[int, int]]      # (offset, tamaño) de cada argumento
    index: int = 0


def store_for(size: int, is_float: bool) -> str:
    if size == 1:
        return "sb"
    return "s.s" if is_float else "sw"


class CallsMixin:
    """Handlers de func_begin, func_end, param, call y return."""

    _pending: Optional[PendingCall] = None

    # ------------------------------------------------------------- llamado

    def callee_record(self, call_pos: int) -> Optional[ActivationRecord]:
        """Registro de activación de la función que llama el `call` en `call_pos`.
        Directa: por su etiqueta. Método virtual: se busca el `method obj, m`
        que produjo la dirección y se toma la etiqueta de `m` en la vtable del
        tipo estático de `obj` (una sobreescritura tiene la misma firma, así que
        sus argumentos ocupan los mismos offsets)."""
        target = self.program.quads[call_pos].arg1
        if isinstance(target, Label):
            return self.record_of(target.name)
        if isinstance(target, Temp):
            lo, _ = self.functions[self.function]
            for i in range(call_pos - 1, lo - 1, -1):
                q = self.program.quads[i]
                if q.op == Op.METHOD and isinstance(q.result, Temp) and q.result.index == target.index:
                    cls = getattr(q.arg1, "type", None)
                    layout = self.table.class_layouts.get(cls.name) if isinstance(cls, ClassType) else None
                    name = q.arg2.name if isinstance(q.arg2, Label) else str(q.arg2)
                    label = layout.method_label(name) if layout else None
                    return self.record_of(label) if label else None
        return None

    @staticmethod
    def argument_slots(callee: Optional[ActivationRecord], args: List[Operand]) -> List[Tuple[int, int]]:
        """(offset dentro del área de argumentos, tamaño) de cada argumento.
        Sale del registro de activación del llamado; si no se conoce, se calcula
        con la misma regla de alineación a partir del tipo de cada argumento."""
        if callee is not None and len(callee.params) == len(args):
            base = callee.params_base
            return [(p.frame_offset - base, p.size) for p in callee.params]
        out, cursor = [], 0
        for a in args:
            if isinstance(a, Const) and isinstance(a.value, bool):
                size = 1
            else:
                size = sizeof(getattr(a, "type", None))
            off = align(cursor, min(size, WORD))
            out.append((off, size))
            cursor = off + size
        return out

    def save_registers(self, regs: List[str]) -> None:
        if not regs:
            return
        self.asm.emit("addiu", "$sp", "$sp", -WORD * len(regs),
                      comment="guardar registros vivos después de la llamada")
        for i, r in enumerate(regs):
            self.asm.emit("s.s" if r.startswith("$f") else "sw", r, f"{WORD * i}($sp)")

    def restore_registers(self, regs: List[str]) -> None:
        if not regs:
            return
        for i, r in enumerate(regs):
            self.asm.emit("l.s" if r.startswith("$f") else "lw", r, f"{WORD * i}($sp)")
        self.asm.emit("addiu", "$sp", "$sp", WORD * len(regs), comment="registros restaurados")

    def begin_call(self, call_pos: int, first_param: int) -> PendingCall:
        args = [q.arg1 for q in self.program.quads[first_param:call_pos]]
        callee = self.callee_record(call_pos)
        slots = self.argument_slots(callee, args)
        area = align(max((off + size for off, size in slots), default=0), WORD)
        saved = self.regs.live_across(call_pos)
        self.save_registers(saved)
        if area:
            self.asm.emit("addiu", "$sp", "$sp", -area,
                          comment=f"{len(args)} argumento(s) para {self.program.quads[call_pos].arg1}")
        return PendingCall(call_pos, callee, saved, area, slots)

    # -------------------------------------------------------- param / call

    def op_param(self, q: Quad, pos: int) -> None:
        if self._pending is None or pos > self._pending.call_pos:
            call_pos = pos
            while self.program.quads[call_pos].op == Op.PARAM:
                call_pos += 1
            if self.program.quads[call_pos].op != Op.CALL:
                raise ValueError(f"param sin call en la instrucción {pos}")
            self._pending = self.begin_call(call_pos, pos)
        call = self._pending
        off, size = call.slots[call.index]
        call.index += 1
        reg = self.regs.load(q.arg1, pos)
        self.asm.emit(store_for(size, reg.startswith("$f")), reg, f"{off}($sp)",
                      comment=f"argumento {call.index - 1}")

    def op_call(self, q: Quad, pos: int) -> None:
        call = self._pending if self._pending and self._pending.call_pos == pos else None
        self._pending = None
        if call is None:                          # llamada sin argumentos
            call = self.begin_call(pos, pos)
        callee = call.callee
        link = 0
        if callee is not None and callee.needs_static_link:
            hops = self.record.level - callee.level + 1
            base = self.frame_base(hops, f"el static link de {callee.label}")
            self.asm.emit("addiu", "$sp", "$sp", -WORD)
            self.asm.emit("sw", base, "0($sp)", comment=f"static link de {callee.label}")
            link = WORD
        if isinstance(q.arg1, Label):
            self.asm.emit("jal", q.arg1.name)
        else:
            self.asm.emit("jalr", self.regs.load(q.arg1, pos), comment="método (despacho dinámico)")
        if call.area + link:
            self.asm.emit("addiu", "$sp", "$sp", call.area + link, comment="liberar argumentos")
        self.restore_registers(call.saved)
        if q.result is not None:
            d = self.regs.dest(q.result, pos)
            self.asm.emit("mov.s" if q.result.is_float else "move", d,
                          "$f0" if q.result.is_float else "$v0", comment="valor de retorno")
            self.regs.store(d, q.result, pos)

    def frame_layout(self, label: str, record: ActivationRecord) -> FrameLayout:
        return FrameLayout(label, record, self.regs.spill_words(label))

    # ------------------------------------------------------- func_begin / end

    def op_func_begin(self, q: Quad, pos: int) -> None:
        label = str(q.arg1)
        record = self.record_of(label)
        if record is None:
            raise ValueError(f"no hay registro de activación para {label}")
        lo, hi = self.functions[label]
        self.function, self.record = label, record
        self.regs.enter_function(label, lo, hi, record)
        self.frame = self.frame_layout(label, record)
        if record is not self.table.main:
            from .translator import MipsNotImplemented
            raise MipsNotImplemented(f"prólogo de la función {label}")
        self.asm.blank()
        self.asm.label("main", comment=f"func_begin main, {q.arg2}")
        self.asm.emit("move", "$fp", "$sp")
        if self.frame.reserve:
            self.asm.emit("addiu", "$sp", "$sp", -self.frame.reserve,
                          comment=f"spill: {self.frame.spill_words} palabra(s)")

    def op_func_end(self, q: Quad, pos: int) -> None:
        self.asm.comment("func_end main")
        self.asm.emit("move", "$sp", "$fp")
        self.asm.emit("li", "$v0", 10)
        self.asm.emit("syscall", comment="exit")
        self.function, self.record = None, None


__all__ = ["CallsMixin", "FrameLayout", "PendingCall"]
