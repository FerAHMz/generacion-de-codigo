# Generación de código MIPS

La tercera fase del compilador traduce el TAC (ver
[LENGUAJE_INTERMEDIO.md](LENGUAJE_INTERMEDIO.md)) a **MIPS32** y lo ejecuta en
**MARS 4.5**. El código está en `compiscript/mips/`:

| Módulo | Contenido |
|---|---|
| `asm.py` | `MipsProgram`: segmentos `.data` y `.text`, literales internados, rutinas del runtime |
| `translator.py` | `MipsTranslator`: recorre el TAC y despacha cada instrucción a su handler `op_<nombre>` |
| `regs.py` | `RegisterManager`: `getReg()` con linear scan o solo pila |
| `memory.py` | área global y acceso a variables (locales, parámetros, globales y no locales por static link) |
| `calls.py` | marcos de pila, prólogo/epílogo y secuencias de llamada y retorno |
| `arith.py`, `control.py`, `data_structs.py`, `objects.py` | traducción de cada instrucción (sección 5) |
| `runtime_lib.py` | rutinas del runtime en MIPS y `concat` (sección 6) |
| `exceptions.py` | pila de manejadores, `push_handler`/`pop_handler`/`exception` y `__raise` (sección 7) |
| `simulator.py` | `run_mars()`: ejecuta un `.asm` en MARS sin GUI (sección 8) |

```python
from compiscript.codegen import compile_source
res = compile_source(src, regalloc="linear")   # o "stack"
print(res.asm)                                 # .asm listo para MARS
```

```bash
make mars                                       # descarga tools/Mars4_5.jar
java -jar tools/Mars4_5.jar nc sm programa.asm  # ejecuta sin GUI
```

---

## 1. Secuencias de llamada y retorno

### 1.1 Marco de pila

La pila crece hacia direcciones bajas. Cada llamada crea un marco
direccionado con `$fp`; su encabezado tiene solo los campos que la función usa
(se decide en `SymbolTable._decide_header`, Proyecto 2):

```
 direcciones altas
        ┌──────────────────────────┐
        │ ...marco del llamador... │
        ├──────────────────────────┤ ◄─ $sp del llamador antes de la llamada
        │ registros $t/$f vivos    │  los guarda el llamador (solo modo linear)
        ├──────────────────────────┤
fp+12   │ argumento 1              │  los escribe el llamador; el 0 queda
fp+8    │ argumento 0  (o `this`)  │  junto al encabezado
        ├──────────────────────────┤
fp+..   │ [static link]            │  lo apila el llamador si el llamado lo usa
fp+4    │ [dirección de retorno]   │  la guarda el prólogo si la función no es hoja
fp+0    │ control link ($fp viejo) │  la guarda el prólogo
        ├──────────────────────────┤ ◄─ $fp
fp-..   │ locales                  │  ActivationRecord.locals (boolean = 1 byte)
fp-..   │ ranuras de spill         │  temporales que no están en un registro
fp-..   │ [$ra extra]              │  hoja que llama a una rutina del runtime
fp-..   │ registros $s usados      │  callee-saved
        └──────────────────────────┘ ◄─ $sp
 direcciones bajas
```

Los offsets del encabezado y de los parámetros salen del `ActivationRecord`
(`header_offset`, `params_base`, `Symbol.frame_offset`), así que el MIPS usa
exactamente las direcciones `fp[±off]` que ya tiene el TAC.

`main` no tiene encabezado: nadie la llama. Sus variables están en el área
global (`__globals` en `.data`) y su marco solo tiene ranuras de spill. Termina
con `move $sp, $fp` y la syscall 10.

### 1.2 Llamada (`param` … `call`)

El generador de TAC evalúa todos los argumentos antes de emitir los `param`,
así que los `param` de una llamada siempre van juntos, justo antes de su
`call`. `CallsMixin` traduce:

| TAC | MIPS |
|---|---|
| primer `param` | guarda los `$t`/`$f` vivos después de la llamada (`live_across`) y reserva el área de argumentos: `addiu $sp, $sp, -área` |
| `param x` (i-ésimo) | `sw`/`s.s`/`sb x, off_i($sp)`; `off_i` y el tamaño salen de los parámetros del llamado |
| `call f, n` | si el llamado tiene static link, se siguen `p − q + 1` enlaces desde `$fp` y se apila; `jal f` (o `jalr` si `f` es la dirección que dejó `method`); `addiu $sp, $sp, área + static link`; se restauran los registros guardados; el resultado se copia de `$v0` (o `$f0` si es float) |

En una llamada virtual (`t = method obj, m` + `call t, n`) el llamado se
conoce en tiempo de ejecución; los offsets de los argumentos se toman del
método `m` en la vtable del tipo estático de `obj`. Una sobreescritura tiene la
misma firma, así que sus parámetros están en los mismos offsets.

### 1.3 Prólogo, retorno y epílogo

```
f:                              # func_begin f
    addiu $sp, $sp, -8          # (-4 si es hoja)
    sw    $ra, 4($sp)           # solo si llama a otras funciones
    sw    $fp, 0($sp)           # control link
    move  $fp, $sp
    addiu $sp, $sp, -reserva    # locales + spill + [$ra extra] + $s
    sw    $s0, -k($fp)          # cada $s que use la función
    ...
    move  $v0, <valor>          # return x   (mov.s $f0 si es float)
    j     __ret_f               # se omite si el return es la última instrucción
__ret_f:                        # func_end f
    lw    $s0, -k($fp)
    move  $sp, $fp
    lw    $fp, 0($sp)
    lw    $ra, 4($sp)
    addiu $sp, $sp, 8
    jr    $ra
```

Una función hoja (sin `$ra` en su encabezado) que usa una instrucción que
llama con `jal` a una rutina del runtime (`MipsTranslator.RUNTIME_CALL_OPS`)
guarda `$ra` en una ranura extra de su marco, sin cambiar los offsets del
encabezado que espera el llamador.

### 1.4 Ejemplo real (`fact`, modo linear)

```
function fact(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * fact(n - 1);
}
```

```
fact:                                   # func_begin fact, 20
        addiu $sp, $sp, -8
        sw $ra, 4($sp)                  # dirección de retorno
        sw $fp, 0($sp)                  # control link
        move $fp, $sp
        addiu $sp, $sp, -4              # locales 0 B, spill 0, $s 1
        sw $s0, -4($fp)                 # callee-saved
        ...
L1:
        # t1 = n                        (vive durante la llamada: va a $s0)
        lw $t8, 8($fp)                  # n
        move $s0, $t8
        ...
        # param t2
        addiu $sp, $sp, -4              # 1 argumento(s) para fact
        sw $t0, 0($sp)                  # argumento 0
        # t2 = call fact, 1
        jal fact
        addiu $sp, $sp, 4               # liberar argumentos
        move $t0, $v0                   # valor de retorno
        # t1 = t1 * t2
        mul $t0, $s0, $t0
        # return t1
        move $v0, $t0                   # valor de retorno
__ret_fact:                             # func_end fact
        lw $s0, -4($fp)
        move $sp, $fp
        lw $fp, 0($sp)                  # control link
        lw $ra, 4($sp)
        addiu $sp, $sp, 8
        jr $ra
```

### 1.5 Variables

Las variables del programa no ocupan registros entre instrucciones; cada
acceso va a memoria (`MemoryMixin`):

| `Var.address` | Operando MIPS |
|---|---|
| `global[off]` | `__globals+off` |
| `fp[+off]` / `fp[-off]` con `hops = 0` | `off($fp)` |
| `fp[±off]` con `hops = k` | `lw $v1, sl($fp)` … k veces por la cadena de static links, luego `off($v1)` |

`boolean` usa `lb`/`sb`, `float` usa `l.s`/`s.s` y lo demás `lw`/`sw`.

---

## 2. Asignación de registros: `getReg()`

### 2.1 Registros

| Uso | Registros |
|---|---|
| Temporales enteros | `$t0–$t7` (los guarda el llamador), `$s0–$s7` (los guarda el llamado) |
| Temporales flotantes | `$f4–$f11`, `$f16–$f28` (los guarda el llamador) |
| Trabajo (scratch) del traductor | `$t8`, `$t9`, `$a3` · `$f29`, `$f30`, `$f31` |
| Direcciones (globales, static links) | `$v1` |
| Retorno | `$v0` / `$f0` |
| Rutinas del runtime y syscalls | `$a0–$a2`, `$v0`, `$f12` |
| Marco | `$sp`, `$fp`, `$ra` |

### 2.2 Modo `linear` (por defecto)

`RegisterManager` usa los intervalos de vida que calcula
`ir/liveness.py` (`live_intervals`, Proyecto 2): análisis de vida hacia
atrás sobre el grafo de flujo de cada función, y definiciones que alcanzan
para separar en valores distintos los usos de un mismo temporal reciclado.
Sobre esos intervalos corre **linear scan** (M. Poletto y V. Sarkar, *Linear
Scan Register Allocation*, ACM TOPLAS 21(5), 1999), una vez por función y por
clase de registro (entera y flotante):

1. Se recorren los intervalos por su inicio; los que ya terminaron liberan su
   registro. Dos intervalos que solo se tocan en un extremo comparten registro
   (`addu $t0, $t0, $t1`).
2. Si hay registro libre: un valor vivo durante un `call` (`crosses_call`) toma
   un `$s`, y así no hay que guardarlo alrededor del `jal`; los demás toman un
   `$t`. Si no queda de su clase preferida, toma el otro.
3. Si no hay registro libre, se derrama (spill) el intervalo que termina más
   tarde: recibe una ranura en el marco.

`getReg(pos, t, rol)` responde para cada aparición de un temporal:

* en un registro → ese registro, sin código extra;
* derramado y leído → `lw $t8, ranura($fp)` (siguiente scratch libre);
* derramado y escrito → un scratch, y `store()` emite `sw scratch, ranura($fp)`.

El prólogo guarda una sola vez los `$s` que usa la función; en cada `call`,
el llamador guarda los `$t`/`$f` que siguen vivos después (`live_across`).

### 2.3 Modo `stack`

Ningún temporal vive en un registro entre instrucciones: `tN` está siempre en
`ActivationRecord.temp_address(N)`. Cada instrucción carga sus operandos en
scratch, opera y guarda el resultado. No hay registros que guardar alrededor
de las llamadas.

```python
compile_source(src, regalloc="stack")
```

### 2.4 Registros de trabajo

Dentro de una instrucción TAC los scratch se reparten en orden (`$t8`, `$t9`,
`$a3`): primero los operandos y después el resultado, así nunca se pisa un
operando antes de leerlo. `RegisterManager.begin(pos)` los libera al empezar
cada instrucción.

---

## 3. Cómo agregar la traducción de una instrucción

Los handlers viven en mixins que hereda `MipsTranslator`. Contrato:

```python
class ArithMixin:
    def op_add(self, q: Quad, pos: int) -> None:      # nombre: translator.OP_NAMES
        a = self.regs.load(q.arg1, pos)                # Temp | Var | Const -> registro
        b = self.regs.load(q.arg2, pos)
        d = self.regs.dest(q.result, pos)              # registro del resultado
        self.asm.emit("addu", d, a, b)
        self.regs.store(d, q.result, pos)              # lo guarda si vive en memoria
```

| Utilidad | Uso |
|---|---|
| `self.regs.load` / `dest` / `store` / `get_reg` / `scratch` | operandos y resultado (sección 2) |
| `self.asm.emit`, `label`, `string(text)`, `float_const(v)`, `data(...)` | código y datos |
| `self.new_label("hint")` | etiqueta interna única (`__hint_N`) |
| `self.runtime_error(kind)` | `la $a0, mensaje` + `j __raise` (mensajes de `ir/runtime.py`) |
| `setup_<algo>()` en un mixin | se llama antes de traducir (p. ej. vtables en `.data`) |
| `RUNTIME_CALL_OPS` | instrucciones que hacen `jal` a una rutina del runtime |

Una instrucción sin handler lanza `MipsNotImplemented`; las pruebas de
extremo a extremo la marcan como skip.

---

## 4. Pruebas

| Archivo | Qué valida |
|---|---|
| `tests/mips/test_translator_base.py` | programa MIPS, despacho, modo pila, constantes, `__raise` sin manejador |
| `tests/mips/test_memory.py` | área global, anchos por tipo, `fp` relativo, cadena de static links, error si falta un static link |
| `tests/mips/test_regs.py` | linear scan (reuso en extremos, spill del que termina más tarde, preferencia `$s`), sin conflictos en todos los ejemplos, spill con 1 y 2 registros sin cambiar la salida |
| `tests/mips/test_calls.py` | offsets de argumentos (boolean de 1 byte), static link con p − q + 1 enlaces, `$t` guardados alrededor de `jal`, `jalr` en métodos, prólogo/epílogo, recursión, recursión mutua, closures, balance de `$sp` y `$fp` en MARS |
| `tests/mips/test_modes.py` | `linear` y `stack` dan la misma salida que el intérprete de TAC |

Las pruebas que ejecutan MARS se saltan si no hay Java o `tools/Mars4_5.jar`
(`make mars`).

---

## 5. Traducción TAC → MIPS

Cada instrucción TAC tiene su handler en un mixin de `compiscript/mips/`:

| Módulo | Instrucciones |
|---|---|
| `arith.py` | `+ - * / %`, `minus`, `not`, `=`, `int_to_float` |
| `control.py` | `< <= > >= == !=`, `label`, `goto`, `if`, `ifFalse`, `if<` … `if!=`, `print` |
| `data_structs.py` | `alloc`, `len`, `[]`, `[]=` |
| `objects.py` | vtables en `.data`, `new`, `getf`, `setf`, `method` |

En las secuencias, `a`, `b`, `i`, `x` y `obj` son los registros que entrega
`RegisterManager.load` (un registro asignado o un scratch ya cargado) y `t` el
de `RegisterManager.dest`; si el resultado vive en memoria, `store` agrega el
`sw`/`s.s`. Además de los scratch, los handlers usan registros que nunca
guardan un temporal entre instrucciones: `$v1` (longitud, dirección del
elemento, vtable, bits del divisor float), `$f2` (cociente de `%` float) y
`$a0`, `$a1`, `$v0` en syscalls y en la comparación de strings.

### 5.1 Tabla de traducción

| TAC | Secuencia MIPS |
|---|---|
| `t = a + b` · `-` · `*` | `addu`/`subu`/`mul t, a, b`; float: `add.s`/`sub.s`/`mul.s t, a, b` |
| `t = a / b` | `bnez b, ok` · `la $a0, __err_division_by_zero` · `j __raise` · `ok:` · `div a, b` · `mflo t`; float: revisión con `mfc1 $v1, b` + `sll $v1, $v1, 1` (ignora el signo de `-0.0`) y `div.s t, a, b` |
| `t = a % b` | revisión de cero · `div a, b` · `mfhi t` (signo del dividendo: `7 % -2 == 1`, como el intérprete) |
| `t = minus a` | `subu t, $zero, a`; float: `neg.s t, a` |
| `t = not a` | `xori t, a, 1` |
| `x = y` | `move` / `mov.s` si los dos están en registros; si no, `lw`/`lb`/`l.s` + `sw`/`sb`/`s.s` (constantes: `li`, `la` o `l.s` desde `.float` en `.data`) |
| `t = int_to_float a` | `mtc1 a, t` · `cvt.s.w t, t` |
| `t = a relop b` | `slt`/`sle`/`sgt`/`sge`/`seq`/`sne t, a, b`; float: `c.lt.s`/`c.le.s`/`c.eq.s` (para `>`/`>=` con los operandos invertidos) · `li t, 1` · `bc1t fin` (`bc1f` en `!=`) · `li t, 0` · `fin:` |
| `a == b` / `a != b` con strings | recorrido en línea byte a byte con `lb` (misma dirección → iguales; uno null → distintos) |
| `L:` · `goto L` | `L:` · `j L` |
| `if a goto L` · `ifFalse a goto L` | `bnez a, L` · `beqz a, L` |
| `if a relop b goto L` | `blt`/`ble`/`bgt`/`bge`/`beq`/`bne a, b, L`; float: `c.xx.s` + `bc1t`/`bc1f L` |
| `print x` | integer: `move $a0, x` + syscall 1 · float: `mov.s $f12, x` + syscall 2 · string: `move $a0, x` (`"null"` si es 0) + syscall 4 · boolean: `la $a0, "true"`/`"false"` según `bnez` + syscall 4 · después `li $a0, 10` + syscall 11 |
| `t = alloc n` | `li $a0, 4 + 4n` (o `sll $a0, n, 2` + `addiu $a0, $a0, 4`) · `li $v0, 9` · `syscall` · `sw n, 0($v0)` · `move t, $v0` |
| `t = len a` | revisión de null · `lw t, 0(a)` |
| `t = a[i]` | `bnez a, ok` (null) · `lw $v1, 0(a)` · `sltu $v1, i, $v1` · `bnez $v1, ok2` (0 ≤ i < len; un `i` negativo es enorme sin signo) · `sll $v1, i, 2` · `addu $v1, a, $v1` · `lw t, 4($v1)` (`l.s` si es float) |
| `a[i] = x` | mismas revisiones y dirección · `sw x, 4($v1)` (`s.s` si es float) |
| vtables | `__vtable_C: .word C_m1, Padre_m2, …` en el orden de `ClassLayout.vtable` (`.word 0` si no tiene métodos) |
| `t = new C, size` | `li $a0, size` · `li $v0, 9` · `syscall` · `la $v1, __vtable_C` · `sw $v1, 0($v0)` · `move t, $v0` |
| `t = [obj + off]` | revisión de null · `lw t, off(obj)` (`lb` si el atributo es boolean, `l.s` si es float) |
| `[obj + off] = x` | revisión de null · `sw x, off(obj)` (`sb` / `s.s`) |
| `t = method obj, m` | revisión de null · `lw $v1, 0(obj)` · `lw t, 4·slot($v1)` con `slot = ClassLayout.method_slot(m)` del tipo estático de `obj`; el `call t, n` siguiente hace `jalr t` |

Las revisiones salen de `runtime.checks_for(op)` y saltan a `__raise` con el
mensaje de `runtime.MESSAGES` en `$a0` (`self.runtime_error`).

### 5.2 Ejemplo real (modo linear)

```cps
let xs = [10, 20];
let i = 1;
let f: float = i * 2.5;
print(xs[i] / 3);
if (f > 2.0) { print(true); }
class A { let x: integer = 1; function g(): integer { return this.x; } }
let a: A = new A();
print(a.g());
```

Extracto del `.asm` que genera `compile_source(src, regalloc="linear").asm`:

```
__vtable_A: .word A_g                   # vtable de A (1 métodos)
...
        # t1 = alloc 2
        li $a0, 12                      # 2 elementos + longitud
        li $v0, 9
        syscall                         # sbrk
        li $v1, 2
        sw $v1, 0($v0)                  # longitud
        move $t0, $v0
        ...
        # t1 = int_to_float t1
        mtc1 $t0, $f4
        cvt.s.w $f4, $f4
        # t1 = t1 * 2.5
        l.s $f30, __flt_5               # 2.5
        mul.s $f4, $f4, $f30
        ...
        # t1 = t1[t2]
        bnez $t0, __ok_6
        la $a0, __err_null_reference
        j __raise                       # acceso a una referencia null
__ok_6:
        lw $v1, 0($t0)                  # longitud
        sltu $v1, $t1, $v1              # 0 <= i < len
        bnez $v1, __ok_7
        la $a0, __err_index_out_of_bounds
        j __raise                       # índice fuera de rango
__ok_7:
        sll $v1, $t1, 2
        addu $v1, $t0, $v1
        lw $t0, 4($v1)
        # t1 = t1 / 3
        li $t8, 3
        bnez $t8, __ok_8
        la $a0, __err_division_by_zero
        j __raise                       # división entre cero
__ok_8:
        div $t0, $t8
        mflo $t0
        ...
        # if t1 <= 2.0 goto L1
        l.s $f30, __flt_9               # 2.0
        c.le.s $f4, $f30
        bc1t L1
        ...
        # t1 = new A, 8
        li $a0, 8                       # new A
        li $v0, 9
        syscall                         # sbrk
        la $v1, __vtable_A
        sw $v1, 0($v0)                  # vtable
        move $s0, $v0
        ...
        # t2 = method t1, g
        bnez $t0, __ok_13
        la $a0, __err_null_reference
        j __raise                       # acceso a una referencia null
__ok_13:
        lw $v1, 0($t0)                  # vtable
        lw $t1, 0($v1)                  # ranura 0: g
        # param t1
        addiu $sp, $sp, -4              # 1 argumento(s) para t2
        sw $t0, 0($sp)                  # argumento 0
        # t1 = call t2, 1
        jalr $t1                        # método (despacho dinámico)
```

### 5.3 Pruebas

| Archivo | Qué valida |
|---|---|
| `tests/mips/test_tr_arith.py` | `div` + `mflo`/`mfhi` después de la revisión de cero, mnemónicos enteros y float, `.float` en `.data`, `mtc1` + `cvt.s.w`, `xori`; en MARS `7 / -2 == -3`, `7 % -2 == 1`, desbordamiento de 32 bits, float, copias y división entre cero sin `try` |
| `tests/mips/test_tr_control.py` | `slt`…`sne`, `c.xx.s` + `bc1t`/`bc1f`, saltos condicionales, syscalls de `print` por tipo; en MARS relacionales, corto circuito, if/else, bucles, break/continue, switch con fallthrough, ternario, `print` por tipo e igualdad de strings |
| `tests/mips/test_tr_arrays.py` | `sbrk` de `4 + 4n` con la longitud en `[base]`, revisión de null e índice antes de `lw`/`sw`, `l.s`/`s.s` en float; en MARS foreach, matriz, arreglos float/boolean/string, arreglo como parámetro, índice fuera de rango (grande, negativo, escritura, matriz) y arreglo null |
| `tests/mips/test_tr_objects.py` | vtables iguales a `ClassLayout.vtable`, `new` con `object_size` y la vtable en `[t + 0]`, `method` con `lw` de la vtable y de la ranura antes del `jalr`, `lb`/`sb` y `l.s`/`s.s` en atributos; en MARS despacho a la subclase (también en un nieto y desde un método del padre), listas enlazadas y `null` en `getf`, `setf` y `method` |

Cada prueba de MARS corre en los modos `linear` y `stack` y compara con
`interp.run`.

---

## 6. Runtime en MIPS (`runtime_lib.py`)

Rutinas escritas a mano que el traductor agrega al final del `.text` (una sola
vez, solo si se usan). Convención: argumentos en `$a0`/`$a1` (float en
`$f12`), resultado en `$v0`; una rutina solo pisa `$a0–$a3`, `$v0`, `$v1`,
`$t8`, `$t9`, `hi`/`lo` y `$f0`, `$f2`, `$f12`. Ningún temporal vive en esos
registros, así que un `jal` a una rutina no obliga a guardar nada.

| Rutina | Entrada | Salida |
|---|---|---|
| `__alloc` | `$a0` = bytes | `$v0` = bloque del heap (`sbrk`, redondeado a múltiplo de 4) |
| `__concat` | `$a0`, `$a1` = strings (0 = `null`) | `$v0` = string nuevo con `a` seguido de `b` |
| `__itoa` | `$a0` = integer | `$v0` = texto decimal (incluye `-2147483648`) |
| `__ftoa` | `$f12` = float | `$v0` = texto con el formato de la syscall 2 (`2.5`, `3.0`, `-0.125`) |
| `__btoa` | `$a0` = boolean | `$v0` = `"true"` / `"false"` |

`__concat` mide los dos strings, reserva `len(a) + len(b) + 1` bytes con
`sbrk` (múltiplo de 4, para que los arreglos y objetos que se reserven después
sigan alineados a palabra) y copia byte a byte; un operando `null` se ve como
`"null"`, igual que `interp.to_text`. `__itoa` trabaja con el valor en
negativo para cubrir `-2^31`. `__ftoa` escribe la parte entera, un punto y
hasta 7 cifras significativas redondeadas, sin ceros finales pero con al
menos una cifra decimal (lo mismo que `Float.toString` de Java, que usa MARS
en la syscall 2, para 10⁻³ ≤ |x| < 10⁷).

### 6.1 `t = concat a, b`

```
        <texto de a en $v0>             # string: move $v0, a · integer: move $a0, a + jal __itoa
                                        # float: mov.s $f12, a + jal __ftoa · boolean: jal __btoa
                                        # null: la $v0, __rt_null
        addiu $sp, $sp, -4
        sw $v0, 0($sp)                  # texto de a (las rutinas pisan $a*/$v*)
        <texto de b en $v0>
        move $a1, $v0
        lw $a0, 0($sp)
        addiu $sp, $sp, 4
        jal __concat
        move t, $v0
```

`CONCAT` está en `RUNTIME_CALL_OPS`: una función hoja que concatena guarda
`$ra` en su marco.

## 7. Excepciones (`exceptions.py`)

```
__htop:    .word __hstack          # siguiente entrada libre
__hstack:  .space 3072             # 256 entradas de (L, $fp, $sp)
__exc_msg: .word 0                 # mensaje de la última excepción
```

| TAC | MIPS (en línea, solo `$t8`/`$t9`) |
|---|---|
| `push_handler L` | `lw $t8, __htop` · si está llena: `j __raise_uncaught` con "demasiados try anidados" · `la $t9, L` · `sw $t9, 0($t8)` · `sw $fp, 4($t8)` · `sw $sp, 8($t8)` · `addiu $t8, $t8, 12` · `sw $t8, __htop` |
| `pop_handler` | `lw $t8, __htop` · `addiu $t8, $t8, -12` · `sw $t8, __htop` |
| `e = exception` | `lw $v0, __exc_msg` · guardar en `e` |

Cada revisión (§5.1) termina en `la $a0, __err_<tipo>` + `j __raise`:

```
__raise:
        lw $t8, __htop
        la $t9, __hstack
        beq $t8, $t9, __raise_uncaught  # sin manejador
        addiu $t8, $t8, -12             # desapilar
        sw $t8, __htop
        sw $a0, __exc_msg
        move $v0, $a0
        lw $fp, 4($t8)                  # marco de la función del try
        lw $sp, 8($t8)
        lw $t9, 0($t8)
        jr $t9                          # al catch
__raise_uncaught:                       # "Error en tiempo de ejecución: " + mensaje + '\n'
        ...
        li $a0, 1
        li $v0, 17                      # termina con código 1
        syscall
```

Restaurar `$fp`/`$sp` descarta de una vez los marcos de todas las funciones
llamadas dentro del `try`, como `del self.frames[h.depth:]` en el intérprete.
El `catch` ve las variables con el valor que tenían al fallar porque siempre
están en memoria; al entrar al `catch` empieza un enunciado nuevo, así que no
hay temporales vivos que recuperar. `return`, `break` y `continue` dentro de
un `try` ya emiten sus `pop_handler` en el TAC.

## 8. Ejecución en MARS (`simulator.py`)

```python
from compiscript.mips.simulator import run_mars
res = run_mars(asm, steps=1_000_000)   # MarsResult
res.stdout, res.exit_code, res.timeout, res.error
```

Escribe el `.asm` en un directorio temporal y corre
`java -Djava.awt.headless=true -jar tools/Mars4_5.jar nc ae2 se3 sm <steps> programa.asm`
(sin GUI y sin ícono de Java). Quita el ruido de MARS (aviso de límite de
pasos, mensajes de error de ensamblado) y devuelve:

| Campo | Valor |
|---|---|
| `stdout` | lo que imprimió el programa |
| `exit_code` | 0, el de la syscall 17 (1 en un error sin `try`), 2 si no ensambla, 3 si falla la simulación |
| `timeout` | `True` si se agotó el límite de pasos o el tiempo de reloj |
| `error` | mensaje de MARS si no ensambló o falló |

`mars_available()` indica si hay Java y jar (`$MARS_JAR` o `tools/Mars4_5.jar`).

## 9. Pruebas del runtime, el Driver, el IDE y extremo a extremo

| Archivo | Qué valida |
|---|---|
| `tests/mips/test_runtime_lib.py` | `simulator.py` (comando headless, limpieza de la salida, código de la syscall 17, límite de pasos, error de ensamblado, acentos de `runtime.MESSAGES`); cada rutina con `.asm` escrito a mano (`__itoa` con `-2^31`, `__ftoa` igual a la syscall 2, `__btoa`, `__concat` con `null`, `__alloc` alineado); que ninguna rutina pise registros con temporales; `concat` en programas; `try/catch` en MARS (error en una función llamada desde el `try`, anidados, sin error, recursión, `break` dentro del `try`, sin `try`) |
| `tests/mips/test_driver_ide.py` | `--mips`, `--out x.asm`, `--regalloc`, `--simulate` (salida, error en ejecución, bucle infinito, sin MARS), error semántico sin `.asm`; `/api/compile` con `mips` y `regalloc`, `/api/run` con `engine: "mars"`, pestaña MIPS y botones |
| `tests/mips/test_e2e.py` | cada `examples/NN_*.cps`, `examples/mips/*.cps` y `program/program.cps` en MARS == `interp.run` en `linear` y `stack`; casos por tema; fallidos: error de compilación → `asm is None`, error en ejecución sin `try` → mensaje y código ≠ 0, bucle infinito → `timeout` |

