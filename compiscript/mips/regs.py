"""Asignación de registros: `getReg()`.

`RegisterManager` decide en qué registro MIPS está cada aparición de un
temporal del TAC y genera las cargas y escrituras de memoria necesarias.

Modo `linear` (por defecto): linear scan de Poletto y Sarkar sobre los
intervalos de vida que calcula `ir/liveness.py` (`live_intervals`), con dos
clases de registros:
  enteros   `$t0–$t7` (los guarda el llamador) y `$s0–$s7` (los guarda el llamado)
  flotantes `$f4–$f11`, `$f16–$f28` (todos los guarda el llamador)
Un valor que está vivo durante un `call` (`crosses_call`) prefiere un `$s`:
así no hay que guardarlo alrededor del `jal`; el prólogo de la función guarda
una sola vez los `$s` que usa. Los demás prefieren un `$t`. Si no queda
registro libre se derrama (spill) el intervalo que termina más tarde: vive en
una ranura del marco y se carga en un registro de trabajo en cada uso.

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

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..ir.liveness import FLOAT_REGISTERS, LiveInterval, live_intervals
from ..ir.tac import Const, Operand, TACProgram, Temp, Var
from ..symbols import WORD, ActivationRecord, SymbolTable

INT_SCRATCH: Sequence[str] = ("$t8", "$t9", "$a3")
FLOAT_SCRATCH: Sequence[str] = ("$f30", "$f31", "$f29")
ADDRESS_SCRATCH = "$v1"

CALLER_SAVED: Tuple[str, ...] = tuple(f"$t{i}" for i in range(8))
CALLEE_SAVED: Tuple[str, ...] = tuple(f"$s{i}" for i in range(8))
INT_POOL: Tuple[str, ...] = CALLER_SAVED + CALLEE_SAVED
FLOAT_POOL: Tuple[str, ...] = tuple(r for r in FLOAT_REGISTERS if r not in FLOAT_SCRATCH)

USE, DEF = "use", "def"
MODES = ("linear", "stack")


def linear_scan(intervals: List[LiveInterval], registers: Sequence[str],
                preferred_for_calls: Sequence[str] = ()) -> int:
    """Linear scan (Poletto y Sarkar, 1999) sobre `intervals` ordenados por inicio.

    Igual que `ir.liveness.linear_scan`, más una preferencia: los intervalos con
    `crosses_call` toman primero un registro de `preferred_for_calls` ($s) y los
    demás uno que no esté en esa lista ($t). Los derramados reciben
    `spill_slot`; devuelve la cantidad de ranuras de spill."""
    order = {r: k for k, r in enumerate(registers)}
    keep = set(preferred_for_calls)
    free = set(registers)
    active: List[LiveInterval] = []          # ordenados por fin
    spills = 0
    for iv in intervals:
        for old in list(active):              # expirar los que terminaron
            if old.end > iv.start:
                break
            active.remove(old)
            free.add(old.location)
        if free:
            first = [r for r in free if (r in keep) == iv.crosses_call]
            pool = first or list(free)
            iv.location = min(pool, key=order.__getitem__)
            free.remove(iv.location)
            active.append(iv)
        else:
            victim = active[-1]
            if victim.end > iv.end:           # derramar el que termina más tarde
                iv.location, victim.location = victim.location, None
                victim.spill_slot, spills = spills, spills + 1
                active.remove(victim)
                active.append(iv)
            else:
                iv.spill_slot, spills = spills, spills + 1
        active.sort(key=lambda x: x.end)
    return spills


@dataclass
class FunctionRegisters:
    """Resultado de la asignación de una función (modo linear)."""

    label: str
    intervals: List[LiveInterval]
    occurrences: Dict[Tuple[int, int, str], LiveInterval]
    spill_slots: int = 0
    saved: List[str] = field(default_factory=list)

    def at(self, pos: int, temp: Temp, role: str) -> LiveInterval:
        iv = self.occurrences.get((pos, temp.index, role))
        if iv is None:
            raise RegisterError(f"t{temp.index} ({role}) no aparece en la instrucción {pos}")
        return iv


class RegisterError(Exception):
    """Uso inválido del asignador (operando que no se puede cargar, scratch agotados)."""


class RegisterManager:
    def __init__(self, translator, program: TACProgram, table: SymbolTable, mode: str = "linear",
                 int_pool: Sequence[str] = INT_POOL, float_pool: Sequence[str] = FLOAT_POOL):
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
        self.int_pool = tuple(int_pool)
        self.float_pool = tuple(float_pool)
        self.allocations: Dict[str, FunctionRegisters] = {}

    @property
    def asm(self):
        return self.tr.asm

    # ------------------------------------------------------------- funciones

    def enter_function(self, label: str, lo: int, hi: int, record: ActivationRecord) -> None:
        """Se llama en `func_begin`: prepara la asignación de la función lo..hi."""
        self.function, self.record = label, record
        if self.mode == "stack":
            top = 0
            for q in self.program.quads[lo:hi + 1]:
                for t in q.temps():
                    top = max(top, t.index)
            self._slots[label] = top
            return
        intervals, occ = live_intervals(self.program, lo, hi, label)
        ints = [iv for iv in intervals if not iv.is_float]
        flts = [iv for iv in intervals if iv.is_float]
        spills = linear_scan(ints, self.int_pool, CALLEE_SAVED)
        fspills = linear_scan(flts, self.float_pool)
        for iv in flts:
            if iv.spill_slot is not None:
                iv.spill_slot += spills
        used = {iv.location for iv in ints if iv.location}
        saved = [] if record is self.table.main else [r for r in CALLEE_SAVED if r in used]
        self.allocations[label] = FunctionRegisters(label, intervals, occ, spills + fspills, saved)
        self._slots[label] = spills + fspills

    def spill_words(self, label: Optional[str] = None) -> int:
        """Palabras de spill que necesita la función: en modo pila una ranura por
        temporal; en modo linear una por intervalo derramado."""
        return self._slots.get(label or self.function, 0)

    def callee_saved(self, label: Optional[str] = None) -> List[str]:
        """Registros `$s` que la función usa y debe preservar (prólogo/epílogo).
        `main` no los guarda: nadie la llama."""
        fa = self.allocations.get(label or self.function)
        return list(fa.saved) if fa else []

    def live_across(self, pos: int) -> List[str]:
        """Registros que el llamador debe guardar alrededor del `call` de la
        posición `pos`: valores vivos antes y después de la llamada que están en
        un `$t` o en un `$f` (los `$s` los preserva el llamado). En modo pila no
        hay ninguno."""
        fa = self.allocations.get(self.function)
        if fa is None:
            return []
        regs = {iv.location for iv in fa.intervals
                if iv.location and iv.start < pos < iv.end and iv.location not in CALLEE_SAVED}
        order = {r: k for k, r in enumerate(self.int_pool + self.float_pool)}
        return sorted(regs, key=lambda r: order.get(r, len(order)))

    def interval(self, pos: int, temp: Temp, role: str = USE) -> Optional[LiveInterval]:
        """Intervalo de vida de la aparición (solo modo linear)."""
        fa = self.allocations.get(self.function)
        return fa.at(pos, temp, role) if fa else None

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
        if self.mode == "stack":
            return -(self.record.temps_base + temp.index * WORD)
        iv = self.interval(pos, temp, role)
        return -(self.record.temps_base + (iv.spill_slot + 1) * WORD)

    def register_of(self, temp: Temp, pos: int, role: str) -> Optional[str]:
        """Registro asignado a la aparición del temporal, o None si vive en memoria."""
        if self.mode == "stack":
            return None
        return self.interval(pos, temp, role).location

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


__all__ = ["ADDRESS_SCRATCH", "CALLEE_SAVED", "CALLER_SAVED", "FLOAT_POOL", "FLOAT_SCRATCH",
           "INT_POOL", "INT_SCRATCH", "MODES", "FunctionRegisters", "RegisterError",
           "RegisterManager", "linear_scan"]
