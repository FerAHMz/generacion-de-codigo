"""Segmento de datos y acceso a las variables del programa.

Las variables no ocupan registros entre instrucciones (§9.3 del lenguaje
intermedio): cada lectura es un `lw`/`l.s`/`lb` desde su dirección y cada
escritura un `sw`/`s.s`/`sb`. La dirección sale de `Var.address`:

  global[off]   ->  __globals+off           (área estática en .data)
  fp[+off]      ->  off($fp)                parámetro del marco actual
  fp[-off]      ->  -off($fp)               local del marco actual
  con hops = k  ->  se siguen k static links desde $fp, en $v1:
                    lw $v1, sl_0($fp) ; lw $v1, sl_1($v1) ; ... ; lw $t8, off($v1)

`sl_i` es el offset del static link en el marco de cada función de la cadena
(depende de qué campos tenga su encabezado), por eso se recorre la cadena de
registros de activación `record -> record.parent`.
"""

from __future__ import annotations

import re
from typing import Tuple

from ..ir.tac import Var
from ..symbols import WORD
from ..types import BOOLEAN
from .regs import ADDRESS_SCRATCH

GLOBALS_LABEL = "__globals"
_ADDRESS = re.compile(r"^(global|fp)\[([+-]?\d+)\]$")


class AddressError(Exception):
    """Dirección de variable que no se puede traducir."""


def parse_address(address: str) -> Tuple[str, int]:
    """`global[8]` -> ("global", 8); `fp[-4]` -> ("fp", -4)."""
    m = _ADDRESS.match(address or "")
    if m is None:
        raise AddressError(f"dirección de variable no soportada: {address!r}")
    return m.group(1), int(m.group(2))


def load_op(var: Var) -> str:
    if var.type == BOOLEAN:
        return "lb"
    return "l.s" if var.is_float else "lw"


def store_op(var: Var) -> str:
    if var.type == BOOLEAN:
        return "sb"
    return "s.s" if var.is_float else "sw"


class MemoryMixin:
    """Área global y `load_var`/`store_var` (los usa `RegisterManager`)."""

    def setup_globals(self) -> None:
        size = max(self.table.globals_size, WORD)
        self.asm.data(GLOBALS_LABEL, ".space", size,
                      comment=f"variables globales ({self.table.globals_size} bytes)")

    def var_address(self, var: Var) -> str:
        """Operando de memoria de la variable (`__globals+8`, `-4($fp)`, `8($v1)`),
        emitiendo antes el recorrido de static links si hace falta."""
        kind, off = parse_address(var.address)
        if kind == "global":
            return f"{GLOBALS_LABEL}+{off}" if off else GLOBALS_LABEL
        return f"{off}({self.frame_base(var.hops, var.name)})"

    def frame_base(self, hops: int, what: str = "") -> str:
        """Registro con la dirección del marco que está `hops` static links arriba
        del actual (`$fp` si hops = 0)."""
        base, record = "$fp", self.record
        for i in range(hops):
            if record is None:
                raise AddressError(f"static link inexistente para {what}")
            sl = record.header_offset("static_link")
            if sl is None:
                raise AddressError(f"{record.label} no tiene static link y se necesita para {what}")
            parent = record.parent
            self.asm.emit("lw", ADDRESS_SCRATCH, f"{sl}({base})",
                          comment=f"static link -> {parent.label if parent else '?'}")
            base, record = ADDRESS_SCRATCH, parent
        return base

    def load_var(self, var: Var, reg: str) -> None:
        self.asm.emit(load_op(var), reg, self.var_address(var), comment=var.name)

    def store_var(self, reg: str, var: Var) -> None:
        self.asm.emit(store_op(var), reg, self.var_address(var), comment=var.name)


__all__ = ["AddressError", "GLOBALS_LABEL", "MemoryMixin", "parse_address"]
