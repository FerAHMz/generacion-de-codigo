"""try/catch en MIPS: pila de manejadores, `push_handler`, `pop_handler`,
`x = exception` y la rutina `__raise` definitiva (docs/LENGUAJE_INTERMEDIO.md §9.4).

Datos en `.data`:

    __htop:    .word __hstack          # siguiente entrada libre
    __hstack:  .space 12 * HANDLER_SLOTS
    __exc_msg: .word 0                 # mensaje de la última excepción

Cada entrada de la pila es (`L`, `$fp`, `$sp`) del marco que ejecutó el
`push_handler L`:

| TAC              | MIPS (en línea, sin `jal`: solo usa `$t8`/`$t9`)                 |
|------------------|------------------------------------------------------------------|
| `push_handler L` | `lw $t8, __htop` · revisión de desborde · `la $t9, L` · `sw $t9, 0($t8)` · `sw $fp, 4($t8)` · `sw $sp, 8($t8)` · `addiu $t8, $t8, 12` · `sw $t8, __htop` |
| `pop_handler`    | `lw $t8, __htop` · `addiu $t8, $t8, -12` · `sw $t8, __htop`      |
| `x = exception`  | `lw x, __exc_msg`                                                |

`__raise` (mensaje en `$a0`; se llega con `j`, no regresa):

* pila vacía → imprime `Error en tiempo de ejecución: <mensaje>` y un salto
  de línea, y termina con la syscall 17 (código 1);
* si no → desapila la entrada, guarda el mensaje en `__exc_msg` (y en `$v0`),
  restaura `$fp` y `$sp` y salta a `L`. Así un error dentro de una función
  llamada desde el `try` descarta todos los marcos intermedios y llega al
  `catch` del llamador, igual que en el intérprete (`Interpreter.raise_error`).

Las variables de Compiscript viven en memoria, así que el `catch` las ve con
el valor que tenían al fallar. Ningún temporal está vivo al entrar al `catch`
(empieza un enunciado nuevo).
"""

from __future__ import annotations

from ..ir.tac import Quad

HANDLER_SLOTS = 256           # try anidados (también por recursión) a la vez
ENTRY = 12                    # bytes por entrada: L, $fp, $sp
ERROR_PREFIX = "Error en tiempo de ejecución: "
OVERFLOW_MESSAGE = "demasiados try anidados"

RAISE = """
__raise:                                # $a0 = mensaje del error (se llega con j)
        lw $t8, __htop
        la $t9, __hstack
        beq $t8, $t9, __raise_uncaught  # sin manejador
        addiu $t8, $t8, -12             # desapilar (L, $fp, $sp)
        sw $t8, __htop
        sw $a0, __exc_msg               # valor de `exception`
        move $v0, $a0
        lw $fp, 4($t8)
        lw $sp, 8($t8)
        lw $t9, 0($t8)
        jr $t9                          # al catch
__raise_uncaught:
        move $t8, $a0
        la $a0, __err_prefix
        li $v0, 4
        syscall
        move $a0, $t8
        li $v0, 4
        syscall
        li $a0, 10
        li $v0, 11
        syscall
        li $a0, 1
        li $v0, 17                      # exit2: termina con código 1
        syscall
"""


class ExceptionsMixin:
    """Handlers de `push_handler`, `pop_handler` y `get_exception`, y `__raise`."""

    def require_raise(self) -> None:
        """Agrega (una vez) la pila de manejadores y la rutina `__raise`."""
        if self.asm.has_routine("__raise"):
            return
        self.asm.data("__htop", ".word", "__hstack", comment="tope de la pila de manejadores")
        self.asm.data("__hstack", ".space", ENTRY * HANDLER_SLOTS, comment="(L, $fp, $sp) por try")
        self.asm.data("__exc_msg", ".word", 0, comment="mensaje de la última excepción")
        self.asm.data("__err_prefix", ".asciiz", f'"{ERROR_PREFIX}"')
        self.asm.data("__err_handlers", ".asciiz", f'"{OVERFLOW_MESSAGE}"')
        self.asm.replace_routine("__raise", RAISE)

    def op_push_handler(self, q: Quad, pos: int) -> None:
        self.require_raise()
        ok = self.new_label("hok")
        self.asm.emit("lw", "$t8", "__htop")
        self.asm.emit("la", "$t9", "__hstack")
        self.asm.emit("addiu", "$t9", "$t9", ENTRY * HANDLER_SLOTS, comment="fin de __hstack")
        self.asm.emit("bne", "$t8", "$t9", ok)
        self.asm.emit("la", "$a0", "__err_handlers")
        self.asm.emit("j", "__raise_uncaught", comment=OVERFLOW_MESSAGE)
        self.asm.label(ok)
        self.asm.emit("la", "$t9", q.result.name)
        self.asm.emit("sw", "$t9", "0($t8)", comment="catch")
        self.asm.emit("sw", "$fp", "4($t8)")
        self.asm.emit("sw", "$sp", "8($t8)")
        self.asm.emit("addiu", "$t8", "$t8", ENTRY)
        self.asm.emit("sw", "$t8", "__htop")

    def op_pop_handler(self, q: Quad, pos: int) -> None:
        self.require_raise()
        self.asm.emit("lw", "$t8", "__htop")
        self.asm.emit("addiu", "$t8", "$t8", -ENTRY)
        self.asm.emit("sw", "$t8", "__htop")

    def op_get_exception(self, q: Quad, pos: int) -> None:
        self.require_raise()
        self.asm.emit("lw", "$v0", "__exc_msg", comment="mensaje de la excepción")
        self.regs.store("$v0", q.result, pos)


__all__ = ["ENTRY", "ERROR_PREFIX", "ExceptionsMixin", "HANDLER_SLOTS", "RAISE"]
