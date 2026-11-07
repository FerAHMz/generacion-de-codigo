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
   traducción de cada instrucción TAC. El `.asm` se ejecuta en MARS.

El diseño del lenguaje intermedio está en [docs/LENGUAJE_INTERMEDIO.md](docs/LENGUAJE_INTERMEDIO.md).
Video del Proyecto 2: <https://youtu.be/PEBvcj3bur4>.

**Integrantes:** Fernando Hernández · Felipe Aguilar · Fernando Rueda

## Ejecución rápida

```bash
make venv                        # crea .venv e instala dependencias
make mars                        # descarga MARS 4.5 en tools/ (requiere Java)
make run F=program/program.cps   # analiza un archivo (.cps)
.venv/bin/python Driver.py program/program.cps --tac       # imprime el TAC numerado
.venv/bin/python Driver.py program/program.cps --runtime   # registros de activación y clases
.venv/bin/python Driver.py program/program.cps --run       # ejecuta el TAC con el intérprete
make test                        # batería de tests (pytest)
make ide                         # IDE web en http://localhost:8080
```

Con el mismo entorno Docker del curso: `make docker-build && make docker-shell`.
Guía completa en [docs/EJECUCION.md](docs/EJECUCION.md).

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
  tree_viz.py               árbol en texto / LISP / JSON / Graphviz
Driver.py                   línea de comandos (--tac, --out, --runtime, --run)
ide/                        IDE web (Flask + CodeMirror): TAC, registros de activación y ejecución
tests/                      batería de tests por grupo de reglas (tests/ir: TAC, tabla e
                            intérprete; tests/tac: Driver, IDE y extremo a extremo)
examples/                   programas válidos (NN_*.cps) y con errores (err_*.cps)
docs/                       arquitectura, ejecución, lenguaje intermedio y rúbricas
Dockerfile, commands/, antlr-4.13.1-complete.jar   entorno Docker del curso
```

## Documentación

* [Lenguaje intermedio: instrucciones, convenciones y esquemas](docs/LENGUAJE_INTERMEDIO.md)
* [Arquitectura de la implementación](docs/ARQUITECTURA.md)
* [Cómo ejecutar el compilador](docs/EJECUCION.md)
* [Rúbrica del Proyecto 2: requisito → archivo → tests → demo](docs/RUBRICA_TAC.md)
* [Rúbrica del Proyecto 1: regla → tests → demo](docs/RUBRICA_TESTS.md)

## División del trabajo

### Proyecto 3 — Generación de código MIPS

| Integrante | Porción | Estado |
|---|---|---|
| Fernando Hernández | Base del proyecto, programa MIPS y despacho por instrucción (`mips/asm.py`, `mips/translator.py`), segmento de datos y acceso a variables (`mips/memory.py`), `getReg()` con linear scan y modo pila (`mips/regs.py`), secuencias de llamada y retorno, prólogo y epílogo (`mips/calls.py`). | En progreso |
| Felipe Aguilar | Traducción de instrucciones: aritmética entera y float, relacionales y saltos, `print`, arreglos, objetos y vtables. | Pendiente |
| Fernando Rueda | Runtime en MIPS (strings, conversión a texto, excepciones), ejecución en MARS, Driver, IDE, pruebas de extremo a extremo y documentación final. | Pendiente |

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
