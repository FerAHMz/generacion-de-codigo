# Compiscript — Generación de Código MIPS

Proyecto 3 del curso **Construcción de Compiladores** (Universidad del Valle de Guatemala).
Compilador de **Compiscript** (subset de TypeScript) construido con **ANTLR 4.13.1** y
**Python 3**. Esta fase traduce el código de tres direcciones del Proyecto 2 a
**MIPS32** y lo ejecuta en el simulador **MARS 4.5**.

Parte de las dos pasadas del Proyecto 2 sobre el mismo árbol:

1. **Análisis semántico** (Proyecto 1): tipos, ámbitos y tabla de símbolos. Si hay
   errores, se reportan y no se genera código.
2. **Generación de código de tres direcciones (TAC)** en cuádruplos, con reciclaje de
   temporales y una tabla de símbolos extendida con direcciones, registros de
   activación y layout de objetos.
3. **Generación de MIPS** (Proyecto 3, `compiscript/mips/`): secuencias de llamada y
   retorno, asignación de registros con `getReg()` (linear scan o solo pila) y
   traducción de cada instrucción TAC. El runtime (strings, conversión a texto y `try/catch`) está escrito en MIPS.
4. **Simulación**: el `.asm` se ejecuta en MARS sin GUI desde Python, el Driver
   (`--simulate`) y el IDE (**Ejecutar en MARS**); las pruebas de extremo a
   extremo comparan su salida con el intérprete de TAC en los dos modos de
   registros.

El diseño del lenguaje intermedio está en [docs/LENGUAJE_INTERMEDIO.md](docs/LENGUAJE_INTERMEDIO.md)
y la generación de MIPS en [docs/MIPS.md](docs/MIPS.md).
Video del Proyecto 3: *(pendiente)*. Video del Proyecto 2: <https://youtu.be/PEBvcj3bur4>.

**Integrantes:** Fernando Hernández · Felipe Aguilar · Fernando Rueda

## Ejecución rápida

```bash
make venv                        # crea .venv e instala dependencias
make mars                        # descarga MARS 4.5 en tools/ (requiere Java)
make run F=program/program.cps   # analiza un archivo (.cps)
.venv/bin/python Driver.py program/program.cps --tac       # imprime el TAC numerado
.venv/bin/python Driver.py program/program.cps --runtime   # registros de activación y clases
.venv/bin/python Driver.py program/program.cps --run       # ejecuta el TAC con el intérprete
.venv/bin/python Driver.py program/program.cps --mips      # imprime el MIPS
.venv/bin/python Driver.py program/program.cps --out prog.asm --regalloc stack   # guarda el .asm
.venv/bin/python Driver.py program/program.cps --simulate  # ejecuta el MIPS en MARS
make test                        # batería de tests (pytest)
make ide                         # IDE web en http://localhost:8080
```

Con el mismo entorno Docker del curso: `make docker-build && make docker-shell`.
Guía completa en [docs/EJECUCION.md](docs/EJECUCION.md).

### Generar MIPS y ejecutarlo en MARS desde Python

```bash
.venv/bin/python - <<'PY'
from compiscript.codegen import compile_file
from compiscript.mips.simulator import run_mars

res = compile_file("examples/mips/08_try_catch.cps", regalloc="linear")   # o "stack"
if res.ok:
    out = run_mars(res.asm)          # MARS 4.5 sin GUI
    print(out.stdout)
    print("código de salida:", out.exit_code)
PY
```

### Generar y ejecutar TAC desde Python

```bash
.venv/bin/python - <<'PY'
from compiscript.codegen import compile_file
from compiscript.ir.interp import run

resultado = compile_file("examples/03_clases_y_herencia.cps")
if resultado.ok:
    print(resultado.program.format())
    print(resultado.table.format_runtime())
    print(run(resultado.program, resultado.table))   # salida del programa
else:
    for error in resultado.errors:
        print(error)
PY
```

## Qué valida

| Grupo | Reglas |
|---|---|
| Sistema de tipos | Aritmética con `integer`/`float` (promoción implícita `integer → float`), lógica con `boolean`, comparaciones compatibles, asignaciones e inicializaciones con el tipo declarado, `const` inicializada e inmutable, listas homogéneas, inferencia de tipos. |
| Ámbitos | Resolución local/global, variables no declaradas, redeclaración en el mismo ámbito, visibilidad en bloques anidados, un entorno por función/clase/bloque/bucle, lectura antes de asignar. |
| Funciones | Número y tipo de argumentos (posicional), tipo de retorno, `return` obligatorio y solo dentro de funciones, recursión, funciones anidadas con captura de closures, funciones y parámetros duplicados. |
| Control de flujo | Condiciones `boolean` en `if`/`while`/`do-while`/`for`/ternario, `case` comparables con el `switch`, `foreach` sobre arreglos, `break`/`continue` solo en bucles. |
| Clases | Atributos y métodos existentes (`.`), constructor con argumentos correctos, `this` solo en métodos, herencia (padre existente, sin ciclos), sobreescritura con la misma firma. |
| Listas | Tipo de elementos, índices `integer` y no negativos, indexar solo arreglos. |
| Generales | Código muerto tras `return`/`break`/`continue`, expresiones sin sentido (operar o imprimir funciones), declaraciones duplicadas. |

Los errores se reportan todos juntos con línea y columna; un error no genera
mensajes en cascada.

## Estructura del repositorio

```
program/Compiscript.g4      gramática ANTLR del curso, extendida con float (+ BNF y program.cps)
compiscript/
  generated/                lexer, parser y visitor generados por ANTLR
  parsing.py                construcción del árbol y captura de errores sintácticos
  types.py                  sistema de tipos y compatibilidad
  symbols.py                tabla de símbolos, entornos, direcciones, registros de
                            activación y layout de clases
  semantic/                 visitor semántico (base, expressions, declarations,
                            functions, control_flow, classes)
  ir/                       TAC: cuádruplos y operandos (tac.py), temporales (temps.py),
                            vida de temporales y linear scan (liveness.py),
                            errores en tiempo de ejecución (runtime.py),
                            intérprete de TAC (interp.py)
  codegen/                  pipeline compile_source y generador TAC por mixins:
                            expressions, control_flow, functions y classes
  mips/                     TAC → MIPS32: programa (asm.py), despacho (translator.py),
                            getReg (regs.py), variables (memory.py), llamadas (calls.py),
                            instrucciones (arith, control, data_structs, objects),
                            runtime en MIPS (runtime_lib.py), try/catch (exceptions.py),
                            ejecución en MARS (simulator.py)
  tree_viz.py               árbol en texto / LISP / JSON / Graphviz
Driver.py                   línea de comandos (--tac, --out, --runtime, --run, --mips,
                            --regalloc, --simulate)
ide/                        IDE web (Flask + CodeMirror): TAC, MIPS, registros de activación
                            y ejecución con el intérprete o en MARS
tests/                      batería de tests por grupo de reglas (tests/ir: TAC, tabla e
                            intérprete; tests/tac: Driver, IDE y extremo a extremo del TAC;
                            tests/mips: traducción, registros, llamadas, runtime y extremo a
                            extremo en MARS)
examples/                   programas válidos (NN_*.cps) y con errores (err_*.cps);
                            examples/mips/: un programa por tema para MIPS
tools/                      Mars4_5.jar (make mars; no se versiona)
docs/                       arquitectura, ejecución, lenguaje intermedio y rúbricas
Dockerfile, commands/, antlr-4.13.1-complete.jar   entorno Docker del curso
```

## Documentación

* [Rúbrica del Proyecto 3: requisito → archivo → tests → demo](docs/RUBRICA_MIPS.md)
* [Generación de MIPS: llamadas, getReg(), traducción, runtime, excepciones y MARS](docs/MIPS.md)
* [Lenguaje intermedio: instrucciones, convenciones y esquemas](docs/LENGUAJE_INTERMEDIO.md)
* [Arquitectura de la implementación](docs/ARQUITECTURA.md)
* [Cómo ejecutar el compilador](docs/EJECUCION.md)
* [Rúbrica del Proyecto 2: requisito → archivo → tests → demo](docs/RUBRICA_TAC.md)
* [Rúbrica del Proyecto 1: regla → tests → demo](docs/RUBRICA_TESTS.md)

## División del trabajo

### Proyecto 3 — Generación de código MIPS

| Integrante | Porción | Estado |
|---|---|---|
| Fernando Hernández | Base del proyecto, programa MIPS y despacho por instrucción (`mips/asm.py`, `mips/translator.py`), segmento de datos y acceso a variables (`mips/memory.py`), `getReg()` con linear scan y modo pila (`mips/regs.py`), secuencias de llamada y retorno, prólogo y epílogo (`mips/calls.py`), pruebas `tests/mips/` de registros, memoria, llamadas y modos, `docs/MIPS.md`. | Terminado |
| Felipe Aguilar | Traducción de instrucciones: aritmética entera y float, relacionales y saltos, `print`, arreglos, objetos y vtables (`mips/arith.py`, `control.py`, `data_structs.py`, `objects.py`), pruebas `tests/mips/test_tr_*.py`, tabla de traducción en `docs/MIPS.md`. | Terminado |
| Fernando Rueda | Ejecución en MARS desde Python (`mips/simulator.py`), runtime en MIPS para strings y conversión a texto (`mips/runtime_lib.py`), pila de manejadores y `__raise` para `try/catch` (`mips/exceptions.py`), Driver (`--mips`, `--out`, `--regalloc`, `--simulate`), IDE (pestaña MIPS, descarga del `.asm`, ejecución en MARS, modo de registros), batería `tests/mips/test_runtime_lib.py`, `test_driver_ide.py` y `test_e2e.py`, `examples/mips/` y documentación final (arquitectura, ejecución y rúbrica). | Terminado |

### Proyecto 2 — Generación de código intermedio

| Integrante | Porción | Estado |
|---|---|---|
| Fernando Hernández | Preparación de la base, anotaciones para la segunda pasada, cuádruplos (`ir/tac.py`), temporales (`ir/temps.py`), vida de temporales y linear scan (`ir/liveness.py`), errores en ejecución (`ir/runtime.py`), direcciones / registros de activación por uso / layout de clases (`symbols.py`), esqueleto del generador (`codegen/base.py`), diseño del lenguaje intermedio y preparación para MIPS. | Terminado |
| Felipe Aguilar | Generador de TAC: expresiones, booleanos con corto circuito, control de flujo, funciones y closures, clases e inicializadores por instancia. Pruebas de contrato en `tests/ir/test_codegen_base.py` e integración de ejemplos. | Terminado |
| Fernando Rueda | Intérprete de TAC con marcos, static link, heap y excepciones (`ir/interp.py`), Driver (`--tac`, `--out`, `--runtime`, `--run`), IDE (`/api/compile`, `/api/run`, pestañas de TAC, registros de activación y salida), batería `tests/tac/` (Driver, IDE y extremo a extremo) y documentación final (arquitectura, ejecución y rúbrica). | Terminado |

### Proyecto 1 — Análisis semántico

| Integrante | Porción |
|---|---|
| Fernando Hernández | Configuración del proyecto (Docker/ANTLR/Makefile), integración del parser, sistema de tipos, tabla de símbolos, visualización del árbol, Driver, ejemplos. |
| Felipe Aguilar | Analizador semántico: base del visitor, expresiones, declaraciones, funciones y closures, control de flujo, clases. |
| Fernando Rueda | Batería de tests, IDE web (backend y frontend), documentación y extensión del lenguaje con `float`. |
