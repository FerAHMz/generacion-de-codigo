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
| `tests/mips/test_translator_base.py` | programa MIPS, despacho, modo pila, constantes, `__raise` provisional |
| `tests/mips/test_memory.py` | área global, anchos por tipo, `fp` relativo, cadena de static links, error si falta un static link |
| `tests/mips/test_regs.py` | linear scan (reuso en extremos, spill del que termina más tarde, preferencia `$s`), sin conflictos en todos los ejemplos, spill con 1 y 2 registros sin cambiar la salida |
| `tests/mips/test_calls.py` | offsets de argumentos (boolean de 1 byte), static link con p − q + 1 enlaces, `$t` guardados alrededor de `jal`, `jalr` en métodos, prólogo/epílogo, recursión, recursión mutua, closures, balance de `$sp` y `$fp` en MARS |
| `tests/mips/test_modes.py` | `linear` y `stack` dan la misma salida que el intérprete de TAC |

Las pruebas que ejecutan MARS se saltan si no hay Java o `tools/Mars4_5.jar`
(`make mars`).
