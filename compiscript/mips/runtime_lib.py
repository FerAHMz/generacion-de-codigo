"""Rutinas del runtime en MIPS para strings y conversión a texto, y el handler
de `concat`.

Convención (decisión del grupo): argumentos en `$a0`/`$a1` (float en `$f12`),
resultado en `$v0`. Una rutina solo pisa `$a0–$a3`, `$v0`, `$v1`, `$t8`, `$t9`,
`hi`/`lo` y los flotantes `$f0`, `$f2`, `$f12`; nunca un registro que pueda
tener un temporal (`$t0–$t7`, `$s0–$s7`, `$f4–$f11`, `$f16–$f28`) ni los
scratch flotantes `$f29–$f31`.

| Rutina     | Entrada        | Salida                                         |
|------------|----------------|------------------------------------------------|
| `__alloc`  | `$a0` = bytes  | `$v0` = bloque nuevo del heap (`sbrk`, múltiplo de 4) |
| `__concat` | `$a0`, `$a1` strings (0 = null) | `$v0` = string nuevo `a ++ b` (`null` se ve como `"null"`) |
| `__itoa`   | `$a0` integer  | `$v0` = string decimal (incluye `-2147483648`) |
| `__ftoa`   | `$f12` float   | `$v0` = string con el formato de la syscall 2 (`2.5`, `3.0`, `-0.125`) |
| `__btoa`   | `$a0` boolean  | `$v0` = `"true"` / `"false"` (constantes en `.data`) |

`__ftoa` escribe la parte entera, un punto y hasta 7 cifras significativas
redondeadas, quitando los ceros finales pero dejando al menos una cifra
decimal (como `Float.toString` de Java, que usa MARS para la syscall 2, en el
rango 10⁻³ ≤ |x| < 10⁷).

Los strings creados en ejecución viven en el heap (`sbrk`, syscall 9) y no se
liberan. Todas las reservas son múltiplos de 4 para que el heap quede alineado
a palabra (los arreglos y objetos usan `lw`/`sw` sobre él).
"""

from __future__ import annotations

from ..ir.tac import Const, Quad
from ..types import BOOLEAN, FLOAT, INTEGER, NULL, STRING
from .arith import type_of

# Datos que usan las rutinas (se agregan una vez a .data).
RUNTIME_DATA = {
    "__rt_null": '"null"',
    "__rt_true": '"true"',
    "__rt_false": '"false"',
}

ALLOC = """
__alloc:                                # $a0 = bytes -> $v0 = bloque (alineado a 4)
        addiu $a0, $a0, 3
        srl $a0, $a0, 2
        sll $a0, $a0, 2
        li $v0, 9                       # sbrk
        syscall
        jr $ra
"""

CONCAT = """
__concat:                               # $a0 = a, $a1 = b -> $v0 = a ++ b
        bnez $a0, __concat_a
        la $a0, __rt_null
__concat_a:
        bnez $a1, __concat_b
        la $a1, __rt_null
__concat_b:
        move $t8, $a0                   # origen de a
        move $t9, $a1                   # origen de b
        li $v1, 1                       # len(a) + len(b) + 1
__concat_len_a:
        lb $v0, 0($a0)
        beqz $v0, __concat_len_b
        addiu $v1, $v1, 1
        addiu $a0, $a0, 1
        j __concat_len_a
__concat_len_b:
        lb $v0, 0($a1)
        beqz $v0, __concat_alloc
        addiu $v1, $v1, 1
        addiu $a1, $a1, 1
        j __concat_len_b
__concat_alloc:
        addiu $a0, $v1, 3               # múltiplo de 4
        srl $a0, $a0, 2
        sll $a0, $a0, 2
        li $v0, 9                       # sbrk
        syscall
        move $v1, $v0                   # destino
__concat_copy_a:
        lb $a0, 0($t8)
        beqz $a0, __concat_copy_b
        sb $a0, 0($v1)
        addiu $t8, $t8, 1
        addiu $v1, $v1, 1
        j __concat_copy_a
__concat_copy_b:
        lb $a0, 0($t9)
        sb $a0, 0($v1)                  # copia también el 0 final
        beqz $a0, __concat_end
        addiu $t9, $t9, 1
        addiu $v1, $v1, 1
        j __concat_copy_b
__concat_end:
        jr $ra
"""

ITOA = """
__itoa:                                 # $a0 = n -> $v0 = string decimal
        move $t8, $a0                   # valor (se trabaja en negativo: cubre -2^31)
        move $t9, $a0                   # signo original
        li $a0, 12                      # "-2147483648" + 0
        li $v0, 9                       # sbrk
        syscall
        addiu $v1, $v0, 11
        sb $zero, 0($v1)                # terminador
        blez $t8, __itoa_neg
        subu $t8, $zero, $t8
__itoa_neg:
        li $a1, 10
__itoa_digit:
        div $t8, $a1                    # residuo <= 0 (signo del dividendo)
        mflo $t8
        mfhi $a0
        subu $a0, $zero, $a0
        addiu $a0, $a0, 48              # '0' + cifra
        addiu $v1, $v1, -1
        sb $a0, 0($v1)
        bnez $t8, __itoa_digit
        bgez $t9, __itoa_end
        li $a0, 45                      # '-'
        addiu $v1, $v1, -1
        sb $a0, 0($v1)
__itoa_end:
        move $v0, $v1
        jr $ra
"""

BTOA = """
__btoa:                                 # $a0 = boolean -> $v0 = "true" / "false"
        la $v0, __rt_true
        bnez $a0, __btoa_end
        la $v0, __rt_false
__btoa_end:
        jr $ra
"""

FTOA = """
__ftoa:                                 # $f12 = x -> $v0 = string (formato de la syscall 2)
        li $a0, 32
        li $v0, 9                       # sbrk: [0..20] salida, [21..31] cifras al revés
        syscall
        move $a2, $v0                   # inicio del buffer
        move $v1, $v0                   # puntero de escritura
        mov.s $f0, $f12
        mtc1 $zero, $f2
        c.lt.s $f0, $f2
        bc1f __ftoa_pos
        neg.s $f0, $f0
        li $a0, 45                      # '-'
        sb $a0, 0($v1)
        addiu $v1, $v1, 1
__ftoa_pos:
        trunc.w.s $f2, $f0
        mfc1 $t8, $f2                   # parte entera
        cvt.s.w $f2, $f2
        sub.s $f0, $f0, $f2             # parte fraccionaria en [0, 1)
        li $t9, 10000000                # p = 10^(7 - cifras enteras), mínimo 10
        move $a1, $t8
        li $a3, 10
__ftoa_count:
        div $t9, $a3
        mflo $t9
        div $a1, $a3
        mflo $a1
        bnez $a1, __ftoa_count
        slti $a1, $t9, 10
        beqz $a1, __ftoa_scale
        li $t9, 10
__ftoa_scale:
        mtc1 $t9, $f2
        cvt.s.w $f2, $f2
        mul.s $f0, $f0, $f2
        round.w.s $f0, $f0
        mfc1 $a1, $f0                   # decimales como entero, 0 <= d <= p
        blt $a1, $t9, __ftoa_int
        subu $a1, $a1, $t9              # el redondeo llegó a 1.0: acarreo
        addiu $t8, $t8, 1
__ftoa_int:
        addiu $a0, $a2, 31              # cifras de la parte entera, al revés
__ftoa_int_digit:
        div $t8, $a3
        mflo $t8
        mfhi $v0
        addiu $v0, $v0, 48
        addiu $a0, $a0, -1
        sb $v0, 0($a0)
        bnez $t8, __ftoa_int_digit
        addiu $t8, $a2, 31
__ftoa_int_copy:
        lb $v0, 0($a0)
        sb $v0, 0($v1)
        addiu $a0, $a0, 1
        addiu $v1, $v1, 1
        bne $a0, $t8, __ftoa_int_copy
        li $v0, 46                      # '.'
        sb $v0, 0($v1)
        addiu $v1, $v1, 1
        div $t9, $a3                    # divisor de la primera cifra decimal: p / 10
        mflo $t9
__ftoa_frac_digit:
        div $a1, $t9
        mflo $v0
        mfhi $a1
        addiu $v0, $v0, 48
        sb $v0, 0($v1)
        addiu $v1, $v1, 1
        div $t9, $a3
        mflo $t9
        bnez $t9, __ftoa_frac_digit
__ftoa_strip:                           # quita ceros finales, deja al menos una cifra
        lb $v0, -1($v1)
        li $t8, 48
        bne $v0, $t8, __ftoa_end
        lb $v0, -2($v1)
        li $t8, 46
        beq $v0, $t8, __ftoa_end
        addiu $v1, $v1, -1
        j __ftoa_strip
__ftoa_end:
        sb $zero, 0($v1)
        move $v0, $a2
        jr $ra
"""

ROUTINES = {"__alloc": ALLOC, "__concat": CONCAT, "__itoa": ITOA, "__ftoa": FTOA, "__btoa": BTOA}

# Conversión a texto de cada tipo: rutina que la hace (None si ya es string).
TO_TEXT = {INTEGER: "__itoa", FLOAT: "__ftoa", BOOLEAN: "__btoa", STRING: None}


def runtime_routine(name: str) -> str:
    """Código de una rutina (con `.data` aparte: ver `RUNTIME_DATA`)."""
    return ROUTINES[name]


def standalone(*names: str) -> str:
    """`.data` + `.text` con las rutinas pedidas, para probarlas con un `main`
    escrito a mano (ver tests/mips/test_runtime_lib.py)."""
    data = "\n".join(f"{label}: .asciiz {value}" for label, value in RUNTIME_DATA.items())
    code = "\n".join(ROUTINES[n].strip("\n") for n in names)
    return data, code


class RuntimeLibMixin:
    """`require_runtime(nombre)` y el handler de `concat`."""

    def require_runtime(self, name: str) -> str:
        """Agrega (una vez) la rutina `name` y sus datos; devuelve su etiqueta."""
        if not self.asm.has_routine(name):
            for label, value in RUNTIME_DATA.items():
                self.asm.data(label, ".asciiz", value)
            self.asm.add_routine(name, ROUTINES[name])
        return name

    def call_runtime(self, name: str, comment: str = "") -> None:
        self.asm.emit("jal", self.require_runtime(name), comment=comment)

    def text_of(self, operand, pos: int) -> None:
        """Deja en `$v0` la dirección del texto de `operand` (como `to_text`)."""
        typ = type_of(operand)
        if isinstance(operand, Const) and operand.value is None or typ == NULL:
            self.asm.emit("la", "$v0", "__rt_null")
            self.require_runtime("__concat")
            return
        if isinstance(operand, Const) and isinstance(operand.value, bool):
            typ = BOOLEAN
        elif isinstance(operand, Const) and isinstance(operand.value, str):
            typ = STRING
        elif isinstance(operand, Const) and isinstance(operand.value, float):
            typ = FLOAT
        elif isinstance(operand, Const) and isinstance(operand.value, int):
            typ = INTEGER
        if typ not in TO_TEXT:
            from .control import unsupported
            unsupported(f"concat con un valor de tipo {typ} (conversión a texto)")
        reg = self.regs.load(operand, pos)
        routine = TO_TEXT[typ]
        if routine is None:
            self.asm.emit("move", "$v0", reg)
        elif typ == FLOAT:
            self.asm.emit("mov.s", "$f12", reg)
            self.call_runtime(routine, comment=f"{operand} a texto")
        else:
            self.asm.emit("move", "$a0", reg)
            self.call_runtime(routine, comment=f"{operand} a texto")

    def op_concat(self, q: Quad, pos: int) -> None:
        """`t = concat a, b`: convierte a texto el operando que no sea string
        (`__itoa`, `__ftoa`, `__btoa`) y llama a `__concat`. El texto de `a` se
        guarda en la pila mientras se convierte `b` (las rutinas pisan `$a*`/`$v*`)."""
        self.text_of(q.arg1, pos)
        self.asm.emit("addiu", "$sp", "$sp", -4)
        self.asm.emit("sw", "$v0", "0($sp)", comment="texto de a")
        self.text_of(q.arg2, pos)
        self.asm.emit("move", "$a1", "$v0")
        self.asm.emit("lw", "$a0", "0($sp)")
        self.asm.emit("addiu", "$sp", "$sp", 4)
        self.call_runtime("__concat")
        self.regs.store("$v0", q.result, pos)


__all__ = ["ROUTINES", "RUNTIME_DATA", "RuntimeLibMixin", "TO_TEXT", "runtime_routine", "standalone"]
