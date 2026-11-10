# Arquitectura de la implementación

## Visión general

El compilador hace **dos pasadas sobre el mismo árbol** de ANTLR y una
**tercera fase sobre el TAC**. La primera pasada (Proyecto 1) valida tipos y
ámbitos y deja anotado cada nodo; la segunda (Proyecto 2) usa esas anotaciones
para emitir código de tres direcciones (TAC); la tercera (Proyecto 3) traduce
el TAC a **MIPS32** y el `.asm` se ejecuta en el simulador **MARS 4.5**. Si la
primera pasada encuentra errores, no se genera TAC ni MIPS.

```
 archivo.cps ──► Lexer/Parser (ANTLR) ──► árbol sintáctico
                                              │
                         ┌────────────────────┘
                         ▼
  Pasada 1   SemanticAnalyzer (compiscript/semantic/)
             ├─ ErrorCollector: errores sintácticos y semánticos
             ├─ SymbolTable: entornos y símbolos
             └─ anotaciones: node_types, node_symbols, node_scopes
                         │  (solo si no hay errores)
                         ▼
             SymbolTable.allocate_storage(): direcciones, etiquetas,
             registros de activación por uso y layout de clases
                         │
                         ▼
  Pasada 2   TACGenerator (compiscript/codegen/) ──► TACProgram (compiscript/ir/tac.py)
                                                         │
                               ┌─────────────────────────┼──────────────────────┐
                               ▼                         ▼                      ▼
                     ir/interp.py (oráculo)      ir/liveness.py         SymbolTable con
                     ejecuta el TAC              intervalos de vida     direcciones y layouts
                                                         │                      │
                                                         ▼                      ▼
  Fase 3     MipsTranslator (compiscript/mips/) ──► MipsProgram (.data + .text + runtime)
             ├─ regs.py: getReg() (linear scan o pila)        │
             ├─ calls.py / memory.py: marcos y variables       ▼
             ├─ arith, control, data_structs, objects    mips/simulator.py
             ├─ runtime_lib.py: __concat, __itoa, ...    run_mars(): MARS 4.5 sin GUI
             └─ exceptions.py: pila de manejadores              │
                                                                ▼
          Driver.py (CLI)                       ide/ (Flask + web)
          --tac --run --mips --out --regalloc   /api/compile (tac, mips) · /api/run (intérprete o MARS)
          --simulate
```

El punto de entrada para todo lo que consume TAC es `compile_source` /
`compile_file` (`compiscript/codegen/__init__.py`), que devuelve un
`CompileResult` con `errors`, `program` (`None` si hubo errores), `table` y
`to_dict()` (el JSON que usa el IDE: `errors`, `tac`, `symbols`, `mips`). El
MIPS se genera a pedido (`result.asm`, `result.mips`) con el modo de registros
de `compile_source(src, regalloc="linear" | "stack")`.

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `program/Compiscript.g4` | Gramática del curso, extendida con el tipo `float` (`FloatLiteral` y `'float'` en `baseType`). |
| `compiscript/generated/` | Lexer, parser y visitor generados por ANTLR 4.13.1 (`make grammar`). |
| `compiscript/parsing.py` | Construye el árbol; redirige los errores de ANTLR al colector. |
| `compiscript/errors.py` | `CompilerError` (fase, línea, columna, mensaje) y `ErrorCollector`. |
| `compiscript/types.py` | Sistema de tipos y reglas de compatibilidad. |
| `compiscript/symbols.py` | Símbolos, entornos (`Scope`) y `SymbolTable`. |
| `compiscript/semantic/` | Visitor semántico, dividido en mixins por área de reglas. |
| `compiscript/tree_viz.py` | Árbol en texto, LISP, JSON y Graphviz DOT/SVG. |
| `compiscript/ir/` | Representación intermedia: cuádruplos (`tac.py`), temporales (`temps.py`), vida de temporales y linear scan (`liveness.py`), errores en ejecución (`runtime.py`) e intérprete (`interp.py`). |
| `compiscript/codegen/` | Segunda pasada: `CodeGenBase` (`base.py`) y mixins de generación (`expressions`, `control_flow`, `functions`, `classes`) combinados en `TACGenerator`. |
| `compiscript/mips/` | Tercera fase: TAC → MIPS32. Programa (`asm.py`), despacho (`translator.py`), `getReg()` (`regs.py`), variables (`memory.py`), llamadas (`calls.py`), traducción por grupo de instrucciones (`arith`, `control`, `data_structs`, `objects`), runtime (`runtime_lib.py`), excepciones (`exceptions.py`) y ejecución en MARS (`simulator.py`). Detalle en [MIPS.md](MIPS.md). |
| `Driver.py` | Interfaz de línea de comandos (análisis, TAC, registros de activación, ejecución, MIPS y simulación en MARS). |
| `ide/` | IDE web (Flask + CodeMirror). |
| `tests/` | Batería de pruebas (pytest): `tests/test_*.py` (semántica), `tests/ir/` (TAC, tabla, temporales, intérprete), `tests/tac/` (Driver, IDE y extremo a extremo del TAC) y `tests/mips/` (traducción, registros, llamadas, runtime, Driver/IDE y extremo a extremo en MARS). |
| `examples/` | Programas válidos e inválidos usados por el IDE y los tests; `examples/mips/` cubre recursión, closures, clases, arreglos, strings, floats, switch y try/catch. |
| `tools/` | `Mars4_5.jar` (`make mars`). |

## Sistema de tipos (`types.py`)

Los tipos son objetos comparables por valor:

* **Primitivos:** `integer`, `float`, `string`, `boolean`, `null`, `void`
  (funciones sin retorno) y `<error>`.
* **`ArrayType(element)`**: `integer[]`, `integer[][]`, `Animal[]`…
* **`ClassType(name, parent)`**: tipo nominal; `is_subclass_of` recorre la
  cadena de herencia.
* **`FunctionType(params, returns)`**: tipo de una función usada como valor;
  permite detectar expresiones sin sentido como `f * 2` o `print(f)`.

El tipo `<error>` es un **tipo veneno**: cuando una subexpresión falla se le
asigna `<error>` y todas las reglas lo aceptan silenciosamente. Así un solo
error (por ejemplo una variable no declarada) produce un único mensaje y no
una cascada.

Reglas de compatibilidad (`is_assignable`, `are_comparable`, `are_orderable`,
`common_type`):

* Asignación exige el mismo tipo; una subclase es asignable a su superclase;
  `null` es asignable a referencias (`string`, arreglos, objetos); `[]` es
  asignable a cualquier arreglo.
* `==`/`!=` exigen tipos iguales, clases relacionadas o comparación con `null`.
* `<`, `<=`, `>`, `>=` exigen `integer` en ambos lados.
* `+` con un `string` en cualquier lado es concatenación (como en TypeScript y
  como usa `program.cps` del curso: `"5 + 1 = " + addFive`). El resto de la
  aritmética exige operandos numéricos (`integer` o `float`).
* **Promoción numérica:** un `integer` puede usarse donde se espera un `float`
  (asignación, argumentos, retorno, elementos de arreglo) y una operación
  aritmética con al menos un `float` produce `float`. Lo inverso es error:
  un `float` nunca se convierte implícitamente a `integer`. `%` y los índices
  de arreglos exigen `integer`.

> La gramática original del curso no definía `float`. Se extendió el lexer con
> `FloatLiteral: [0-9]+ '.' [0-9]+` y `baseType` con `'float'` para cubrir el
> requerimiento "los operandos deben ser de tipo `integer` o `float`".

## Tabla de símbolos (`symbols.py`)

### Símbolos

`Symbol(name, kind, type, line, column, scope, initialized, offset, captured)`.
Categorías (`SymbolKind`): `variable`, `constant`, `parameter`, `function`,
`method`, `class`, `field`. Dos especializaciones:

* `FunctionSymbol`: parámetros, tipo de retorno, entorno del cuerpo, variables
  capturadas (closures) y si tiene `return` con valor.
* `ClassSymbol`: clase padre y entorno de miembros; `lookup_member` busca por
  la cadena de herencia y `constructor()` devuelve el constructor si existe.

Cada símbolo guarda además `size` y `offset` dentro de su entorno, pensados
para la fase de generación de código.

### Entornos

`Scope(kind, parent, owner)` con `kind ∈ {global, function, class, block,
loop, switch}`. Se crea un entorno nuevo por **cada función, clase, bloque,
bucle, `case` y `catch`**. Operaciones:

* `define(sym)` → `False` si ya existe en ese entorno (redeclaración).
* `resolve(name)` recorre la cadena de padres (local → global).
* `enclosing_function()`, `enclosing_class()`, `in_loop()`, `in_breakable()`
  responden preguntas de contexto (¿estoy en una función?, ¿en un bucle?),
  deteniéndose en el límite de la función para que un `break` dentro de una
  función anidada en un bucle sea error.

`SymbolTable` mantiene el entorno global, el actual (`push`/`pop`) y la lista
completa de entornos creados, que el IDE y el Driver muestran como tabla.

## Analizador semántico (`semantic/`)

`SemanticAnalyzer` hereda del `CompiscriptVisitor` generado y combina mixins:

| Archivo | Reglas |
|---|---|
| `base.py` | Reporte de errores, resolución de anotaciones de tipo, recorrido de listas de sentencias con **detección de código muerto**, entornos de bloque, **hoisting**. |
| `expressions.py` | Tipado de literales, arreglos, unarios, binarios (aritmética, lógica, comparaciones), ternario, asignaciones como expresión, llamadas (número y tipo de argumentos), `new`, `this`, índices, acceso a miembros y **captura de closures**. |
| `declarations.py` | `let`/`var`/`const` (tipo declarado vs. inferido, `const` inicializada), asignaciones como sentencia, `print`. |
| `functions.py` | Firma y cuerpo de funciones, parámetros duplicados, `return` (dentro de función, tipo correcto, obligatorio si hay tipo de retorno), recursión y funciones anidadas. |
| `control_flow.py` | Condiciones booleanas en `if/while/do-while/for`, entornos de bucle, `foreach` sobre arreglos, `switch` con `case` comparables, `try/catch`, `break`/`continue` solo en bucles. |
| `classes.py` | Herencia (padre existente, sin ciclos), miembros, constructor, sobreescritura con la misma firma, `this` solo en métodos. |

Cada `visitXxx` de expresión devuelve el `Type` calculado y lo registra en
`node_types` (el IDE lo muestra en el árbol).

### Hoisting

Antes de visitar las sentencias de un bloque se registran los **nombres de las
clases** y las **firmas de las funciones** de ese bloque. Esto permite llamar a
una función declarada más abajo, usar una clase como tipo antes de su
declaración y que los métodos de una clase se invoquen entre sí sin importar
el orden. Las redeclaraciones se detectan en este mismo paso.

### Código muerto

`visit_statements` marca como inalcanzable la primera sentencia que sigue a un
`return`, `break` o `continue` dentro del mismo bloque. Un `return` dentro de
un `if` no hace muerto lo que sigue al `if`.

## IDE (`ide/`)

* **Backend** (`app.py`): Flask.
  * `POST /api/analyze`: errores, filas de la tabla de símbolos, entornos y el
    árbol en JSON (Proyecto 1).
  * `POST /api/compile`: `CompileResult.to_dict()` → `{"errors", "tac",
    "symbols"}`; `symbols` trae `activation_records` (encabezado con el uso de
    cada campo, slots y `frame_size`) y `classes` (atributos y vtable). Con
    errores, `tac` es una lista vacía.
  * `POST /api/run`: compila y ejecuta el TAC con el intérprete; devuelve la
    salida de los `print` y, si lo hay, el error en ejecución. Usa un límite de
    pasos para que un bucle infinito no bloquee el servidor.
  * `POST /api/tree.svg` genera la imagen con Graphviz y `GET /api/examples`
    sirve `examples/`.
* **Frontend** (`static/`): CodeMirror con resaltado, marcadores de error en el
  gutter y la línea, y pestañas: errores (clic → salta a la línea), **código
  intermedio** (TAC numerado), **registros de activación** (un cuadro por
  función con su encabezado por uso y el layout de cada clase), **salida**
  (botón *Ejecutar TAC*), tabla de símbolos y árbol colapsable. El análisis y
  la generación se ejecutan en vivo mientras se escribe.

## Segunda pasada: código intermedio

### Representación (`ir/tac.py`)

Cada instrucción es un `Quad(op, arg1, arg2, result)` con operandos tipados
(`Temp`, `Var`, `Const`, `Label`, `Field`), no texto. Así el intérprete, el
análisis de vida y la futura traducción a MIPS trabajan sobre objetos y no
vuelven a parsear cadenas. `Var` guarda su dirección (`global[8]`, `fp[+8]`,
`fp[-4]`) y `hops` (static links a seguir en closures); `Temp` y `Var` llevan
su tipo para separar registros enteros y flotantes. `TACProgram.check()`
verifica etiquetas únicas, saltos a etiquetas existentes y `func_begin`/
`func_end` balanceados. El conjunto de instrucciones y los esquemas de
traducción están en [LENGUAJE_INTERMEDIO.md](LENGUAJE_INTERMEDIO.md).

### Tabla de símbolos para tiempo de ejecución (`symbols.py`)

`SymbolTable.allocate_storage()` se ejecuta al terminar la pasada semántica:

* **Direcciones:** globales en el área estática, parámetros en `fp[+off]`,
  locales (bloques anidados aplanados) en `fp[-off]`, atributos como
  desplazamiento dentro del objeto. Tamaños de MIPS32 (`boolean` = 1 B, el
  resto 4 B), con alineación.
* **Registros de activación por uso** (`ActivationRecord`): el encabezado no
  es fijo. El control link está en todas las funciones salvo `main`; la
  dirección de retorno solo si la función llama a otras (`FunctionSymbol.calls`,
  grafo de llamadas de la pasada 1); el static link solo si la función o una
  anidada lee variables de una función externa, o llama a una función que lo
  necesita (punto fijo sobre el grafo de llamadas). `level` es la profundidad
  léxica (`main` = 0). Los temporales ocupan una ranura cada uno, al final del
  marco.
* **Layout de clases** (`ClassLayout`): `[obj + 0]` apunta a la vtable;
  atributos heredados con los mismos offsets que en el padre; un método
  sobreescrito reemplaza la etiqueta en la misma ranura de la vtable.

### Generador (`codegen/`)

`CodeGenBase` es un visitor del árbol que ofrece la infraestructura: emisión,
etiquetas únicas, un búfer y un `TempAllocator` por función
(`with self.function(record)`), pila de destinos de `break`/`continue` y de
manejadores de `try` (emite los `pop_handler` necesarios en salidas
anticipadas). `TACGenerator` combina los mixins:

| Mixin | Traduce |
|---|---|
| `expressions.py` | literales, variables, aritmética, `concat`, `int_to_float`, asignaciones, arreglos, booleanos con corto circuito (`gen_cond` con etiquetas heredadas y fall-through) |
| `control_flow.py` | `if`, `while`, `do-while`, `for`, `foreach`, `switch`, `break`/`continue`, `try/catch` |
| `functions.py` | declaración de funciones, `param`/`call`, `return` |
| `classes.py` | `new`, inicializadores por instancia (`$init_Clase`), constructor, despacho dinámico con `method` |

### Temporales

* **Al generar** (`ir/temps.py`): free-list que siempre entrega el temporal
  libre de menor número; los operandos se liberan antes de pedir el temporal
  del resultado (`t1 = t1 + c`). La cantidad de temporales distintos de cada
  función (`max_live`) define las ranuras del marco.
* **Sobre el TAC** (`ir/liveness.py`): análisis de vida hacia atrás sobre el
  grafo de flujo de cada función e intervalos de vida por valor, y asignación
  de registros por *linear scan* (Poletto y Sarkar, 1999), con spill del
  intervalo que termina más tarde. Es la base de `getReg()` para la fase de
  MIPS.

### Intérprete (`ir/interp.py`)

Ejecuta el TAC para comprobar que la traducción conserva el significado del
programa (`tests/tac/test_e2e.py`) y fija la semántica que tendrá que respetar
la fase de MIPS:

* memoria por dirección: un diccionario para el área global y uno por marco;
  una `Var` con `hops = k` sigue `k` static links desde el marco actual;
* un marco por llamada con su `ActivationRecord`, sus temporales, control link
  y static link (desde el llamador de nivel `p` hacia el llamado de nivel `q`
  se siguen `p - q + 1` enlaces, como en §6 de LENGUAJE_INTERMEDIO.md);
* heap de arreglos (`alloc`, `len`, `[]`, `[]=`) y objetos (`new` guarda la
  clase; `method` busca la etiqueta en `table.class_layouts[...].vtable`);
* enteros de 32 bits en complemento a dos y `/` entera que trunca hacia cero;
* antes de cada instrucción revisa `runtime.checks_for(op)`; un error salta
  al manejador más reciente (`push_handler`), descartando los marcos y los
  `param` pendientes de las funciones llamadas dentro del `try`, y `x =
  exception` recibe el mensaje. Sin manejador, el programa termina y el
  mensaje queda como última línea de salida;
* un límite de pasos (`max_steps`) detiene programas que no terminan.

## Tercera fase: generación de MIPS (`compiscript/mips/`)

`generate_mips(program, table, regalloc)` crea un `MipsTranslator` y recorre
los cuádruplos una sola vez. Cada instrucción TAC `op` se despacha a un método
`op_<nombre>` definido en un mixin (`translator.OP_NAMES`); los mixins pueden
preparar `.data` antes de traducir con métodos `setup_*` (vtables, área
global). Una instrucción sin traducción lanza `MipsNotImplemented`.

| Pieza | Módulo | Qué decide |
|---|---|---|
| Programa | `asm.py` (`MipsProgram`) | `.data` (strings internados, `.float`, `.space`), `.text` y rutinas del runtime agregadas una sola vez al final |
| `getReg()` | `regs.py` (`RegisterManager`) | registro o ranura de cada aparición de un temporal; linear scan por función y por clase (`$t`/`$s`, `$f`) o todo en pila |
| Variables | `memory.py` | operando de cada `Var`: `__globals+off`, `off($fp)` o la cadena de static links |
| Llamadas | `calls.py` | marco, prólogo/epílogo, área de argumentos, static link, `$t` vivos alrededor de `jal`, `jalr` en métodos |
| Instrucciones | `arith.py`, `control.py`, `data_structs.py`, `objects.py` | secuencias MIPS de cada instrucción, con las revisiones de `runtime.checks_for(op)` |
| Runtime | `runtime_lib.py` | rutinas en MIPS para `concat` y conversión a texto (`__concat`, `__itoa`, `__ftoa`, `__btoa`, `__alloc`) |
| Excepciones | `exceptions.py` | pila de manejadores en `.data`, `push_handler`/`pop_handler`/`exception` en línea y `__raise` |
| Simulación | `simulator.py` | `run_mars(asm)`: archivo temporal, `java -jar Mars4_5.jar nc ae2 se3 sm N`, JVM headless, salida limpia, código de salida y límite de pasos |

### Runtime y convención de las rutinas

Las rutinas reciben argumentos en `$a0`/`$a1` (float en `$f12`) y devuelven
el resultado en `$v0`; solo pueden pisar `$a*`, `$v*`, `$t8`, `$t9` y los
flotantes `$f0`, `$f2`, `$f12`. Así un `jal __concat` no obliga a guardar
ningún temporal: los temporales viven en `$t0–$t7`, `$s0–$s7` y `$f4–$f11`,
`$f16–$f28`. Una función hoja que usa una de estas instrucciones guarda `$ra`
en una ranura extra de su marco (`RUNTIME_CALL_OPS`).

`t = concat a, b` convierte a texto el operando que no es string (con la misma
forma que `interp.to_text`: `true`/`false`, `null`, decimal, float como la
syscall 2), guarda el texto de `a` en la pila mientras convierte `b` y llama a
`__concat`, que reserva `len(a) + len(b) + 1` bytes en el heap con `sbrk`
(redondeado a múltiplo de 4 para no desalinear los arreglos y objetos que se
reserven después) y copia los dos strings.

### Excepciones

Sigue el modelo del intérprete (`Interpreter.raise_error`, LENGUAJE_INTERMEDIO
§9.4). `push_handler L` apila (`L`, `$fp`, `$sp`) en `__hstack` (256
entradas); `pop_handler` desapila. Las revisiones (`null`, índice, división
entre cero) saltan con `j __raise` y el mensaje de `runtime.MESSAGES` en `$a0`.
`__raise`:

* sin manejador: imprime `Error en tiempo de ejecución: <mensaje>` y termina
  con la syscall 17 (código 1), igual que la última línea del intérprete;
* con manejador: lo desapila, deja el mensaje en `__exc_msg`, restaura `$fp` y
  `$sp` (esto descarta de una vez todos los marcos de las funciones llamadas
  dentro del `try`) y salta a `L`, donde `e = exception` lee `__exc_msg`.

### Pruebas diferenciales

El intérprete de TAC es el oráculo de la fase 3: `tests/mips/test_e2e.py`
compila cada ejemplo en los modos `linear` y `stack`, lo ejecuta en MARS y
exige la misma salida y el mismo código de salida que `interp.run`. Los floats
de las pruebas usan valores exactos en binario (0.5, 2.25, …) porque MARS
calcula en precisión simple y el intérprete en doble.

## Árbol sintáctico (`tree_viz.py`)

El árbol de ANTLR se puede ver en cuatro formas: texto indentado (`--tree`),
notación LISP (`--lisp`), JSON (IDE) y Graphviz (`--dot`, SVG/PNG). Para las
representaciones gráficas se colapsan las cadenas de reglas con un solo hijo
(`expression → assignmentExpr → … → primaryExpr`) para que el dibujo sea legible.

![Árbol de ejemplo](img/arbol-ejemplo.png)

## Decisiones de diseño

* **Tipo veneno** para evitar cascadas de errores.
* **`+` concatena** cuando un operando es `string` (compatibilidad con el
  programa de ejemplo del curso).
* **`break` en `switch`** se acepta (semántica de TypeScript); `continue` solo
  en bucles.
* La variable de `catch` se tipa como `string`.
* Una variable declarada sin valor debe recibir una asignación antes de leerse
  (análisis independiente del flujo: basta una asignación previa en el código).
* No se genera TAC para programas con errores: la pasada 2 supone un árbol
  válido y completamente anotado.
* Despacho dinámico por vtable para métodos (una variable `Animal` puede
  contener un `Perro`) y static link para closures (una función anidada nunca
  sobrevive al marco que la contiene).
* **MIPS desde el TAC, no desde el árbol**: la fase 3 solo ve cuádruplos y la
  tabla de símbolos con direcciones, así que el intérprete de TAC sirve de
  oráculo para cada programa.
* **Variables en memoria, temporales en registros**: las variables del
  programa se leen y escriben en su dirección en cada acceso; solo los
  temporales pasan por `getReg()`. Esto hace correcto el `catch` (ve el valor
  de las variables al fallar) y los closures (leen por static link).
* **Rutinas del runtime con registros acotados** en vez de guardar todo
  alrededor de cada `jal`.
* **MARS sin GUI y con la JVM headless** para que la batería no abra ventanas.
* Los archivos generados por ANTLR se versionan para que el proyecto corra sin
  Java; `make grammar` los regenera si la gramática cambia.
