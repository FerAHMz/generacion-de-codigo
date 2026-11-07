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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..ir.tac import Quad
from ..symbols import WORD, ActivationRecord


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


class CallsMixin:
    """Handlers de func_begin, func_end, param, call y return."""

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


__all__ = ["CallsMixin", "FrameLayout"]
