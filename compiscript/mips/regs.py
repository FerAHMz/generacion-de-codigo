"""Asignación de registros: `getReg()`.

`RegisterManager` decide en qué registro MIPS está cada aparición de un
temporal del TAC y genera las cargas y escrituras de memoria necesarias.

Modo `stack`: ningún temporal vive en un registro entre instrucciones. Cada
temporal `tN` tiene su ranura en el marco (`ActivationRecord.temp_address(N)`,
debajo de los locales); para usarlo se carga en un registro de trabajo
(`lw`/`l.s`), se opera y el resultado se vuelve a guardar (`sw`/`s.s`).

Registros de trabajo (scratch), nunca asignados a temporales:
  enteros  `$t8`, `$t9`, `$a3`   flotantes `$f30`, `$f31`, `$f29`
`$v1` se reserva para calcular direcciones (globales y static links).
Dentro de una instrucción TAC los scratch se reparten en orden: el primer
operando que lo necesite recibe `$t8`, el segundo `$t9`, el resultado el
siguiente libre. Así nunca se pisa un operando antes de leerlo.

Uso desde un handler de instrucción (contrato con los mixins de traducción):

    a = self.regs.load(q.arg1, pos)          # Temp | Var | Const -> registro
    b = self.regs.load(q.arg2, pos)
    d = self.regs.dest(q.result, pos)        # registro donde escribir el resultado
    self.asm.emit("addu", d, a, b)
    self.regs.store(d, q.result, pos)        # lo guarda si vive en memoria
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..ir.tac import Const, Operand, TACProgram, Temp, Var
from ..symbols import WORD, ActivationRecord, SymbolTable

INT_SCRATCH: Sequence[str] = ("$t8", "$t9", "$a3")
FLOAT_SCRATCH: Sequence[str] = ("$f30", "$f31", "$f29")
ADDRESS_SCRATCH = "$v1"

USE, DEF = "use", "def"
MODES = ("stack",)


class RegisterError(Exception):
    """Uso inválido del asignador (operando que no se puede cargar, scratch agotados)."""


class RegisterManager:
    def __init__(self, translator, program: TACProgram, table: SymbolTable, mode: str = "stack"):
        if mode not in MODES:
            raise ValueError(f"modo de asignación desconocido: {mode!r} (opciones: {', '.join(MODES)})")
        self.tr = translator
        self.program = program
        self.table = table
        self.mode = mode
        self.record: Optional[ActivationRecord] = None
        self.function: Optional[str] = None
        self._next_int = 0
        self._next_float = 0
        self._slots: Dict[str, int] = {}

    @property
    def asm(self):
        return self.tr.asm

    # ------------------------------------------------------------- funciones

    def enter_function(self, label: str, lo: int, hi: int, record: ActivationRecord) -> None:
        """Se llama en `func_begin`: prepara la asignación de la función lo..hi."""
        self.function, self.record = label, record
        top = 0
        for q in self.program.quads[lo:hi + 1]:
            for t in q.temps():
                top = max(top, t.index)
        self._slots[label] = top

    def spill_words(self, label: Optional[str] = None) -> int:
        """Palabras de spill que necesita la función (ranuras de temporales)."""
        return self._slots.get(label or self.function, 0)

    def callee_saved(self, label: Optional[str] = None) -> List[str]:
        """Registros `$s` que la función usa y debe preservar (prólogo/epílogo)."""
        return []

    def live_across(self, pos: int) -> List[str]:
        """Registros con valores vivos durante el `call` de la posición `pos` que
        el llamador debe guardar. En modo pila no hay ninguno."""
        return []

    # ----------------------------------------------------------- instrucción

    def begin(self, pos: int) -> None:
        """Se llama antes de traducir cada instrucción: libera los scratch."""
        self._next_int = 0
        self._next_float = 0

    def scratch(self, is_float: bool = False) -> str:
        """Siguiente registro de trabajo libre en esta instrucción."""
        if is_float:
            if self._next_float >= len(FLOAT_SCRATCH):
                raise RegisterError("se agotaron los registros de trabajo flotantes")
            reg = FLOAT_SCRATCH[self._next_float]
            self._next_float += 1
        else:
            if self._next_int >= len(INT_SCRATCH):
                raise RegisterError("se agotaron los registros de trabajo enteros")
            reg = INT_SCRATCH[self._next_int]
            self._next_int += 1
        return reg

    # ----------------------------------------------------------------- getReg

    def slot_offset(self, temp: Temp, pos: int, role: str) -> int:
        """Offset (respecto a $fp, negativo) de la ranura de spill del temporal."""
        return -(self.record.temps_base + temp.index * WORD)

    def register_of(self, temp: Temp, pos: int, role: str) -> Optional[str]:
        """Registro asignado a la aparición del temporal, o None si vive en memoria."""
        return None

    def get_reg(self, pos: int, temp: Temp, role: str = USE) -> str:
        """`getReg()`: registro para la aparición de `temp` en la instrucción `pos`.
        Con `role="use"` el registro ya tiene el valor (se carga si estaba en
        memoria); con `role="def"` es donde se escribe el resultado (después hay
        que llamar a `store`)."""
        reg = self.register_of(temp, pos, role)
        if reg is not None:
            return reg
        reg = self.scratch(temp.is_float)
        if role == USE:
            op = "l.s" if temp.is_float else "lw"
            self.asm.emit(op, reg, f"{self.slot_offset(temp, pos, role)}($fp)", comment=f"{temp} (spill)")
        return reg

    def load(self, operand: Operand, pos: int) -> str:
        """Registro con el valor de `operand` (Temp, Var o Const)."""
        if isinstance(operand, Temp):
            return self.get_reg(pos, operand, USE)
        if isinstance(operand, Var):
            reg = self.scratch(operand.is_float)
            self.tr.load_var(operand, reg)
            return reg
        if isinstance(operand, Const):
            reg = self.scratch(operand.is_float)
            self.load_const(operand, reg)
            return reg
        raise RegisterError(f"operando que no se puede cargar en un registro: {operand!r}")

    def load_const(self, c: Const, reg: str) -> None:
        v = c.value
        if v is None:
            self.asm.emit("move", reg, "$zero", comment="null")
        elif isinstance(v, bool):
            self.asm.emit("li", reg, 1 if v else 0, comment=str(c))
        elif isinstance(v, int):
            self.asm.emit("li", reg, v)
        elif isinstance(v, float):
            self.asm.emit("l.s", reg, self.asm.float_const(v), comment=str(c))
        elif isinstance(v, str):
            self.asm.emit("la", reg, self.asm.string(v), comment=str(c)[:30])
        else:
            raise RegisterError(f"constante no soportada: {c!r}")

    def dest(self, operand: Operand, pos: int) -> str:
        """Registro donde escribir el resultado de la instrucción (Temp o Var)."""
        if isinstance(operand, Temp):
            return self.get_reg(pos, operand, DEF)
        if isinstance(operand, Var):
            return self.scratch(operand.is_float)
        raise RegisterError(f"destino inválido: {operand!r}")

    def store(self, reg: str, operand: Operand, pos: int) -> None:
        """Deja en `operand` el valor de `reg` (resultado de la instrucción `pos`)."""
        if isinstance(operand, Temp):
            home = self.register_of(operand, pos, DEF)
            if home is None:
                op = "s.s" if operand.is_float else "sw"
                self.asm.emit(op, reg, f"{self.slot_offset(operand, pos, DEF)}($fp)",
                              comment=f"{operand} (spill)")
            elif home != reg:
                self.asm.emit("mov.s" if operand.is_float else "move", home, reg)
        elif isinstance(operand, Var):
            self.tr.store_var(reg, operand)
        else:
            raise RegisterError(f"destino inválido: {operand!r}")


__all__ = ["ADDRESS_SCRATCH", "FLOAT_SCRATCH", "INT_SCRATCH", "MODES", "RegisterError",
           "RegisterManager"]
