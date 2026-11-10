# Cómo ejecutar el compilador

## Requisitos

* **Opción local:** Python 3.9+ y Java 17+ (para ejecutar el MIPS en MARS y
  para regenerar el parser). Graphviz (`dot`) es opcional para exportar el
  árbol como imagen.
* **MARS 4.5** (simulador de MIPS): `make mars` lo descarga en
  `tools/Mars4_5.jar`. Sin Java o sin el jar, todo funciona salvo la
  simulación (las pruebas que ejecutan MARS se saltan).
* **Opción Docker:** Docker o Rancher Desktop (mismo `Dockerfile` del curso).

## Opción local

```bash
make venv                       # crea .venv e instala requirements.txt
make mars                       # descarga tools/Mars4_5.jar (MARS 4.5)
make grammar                    # (opcional) regenera compiscript/generated desde la gramática
make run F=program/program.cps  # analiza un archivo
make test                       # corre la batería de tests
make ide                        # levanta el IDE en http://localhost:8080 (make ide PORT=9999 para otro puerto)
```

Sin `make`:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python Driver.py program/program.cps
.venv/bin/python -m pytest -q
.venv/bin/python -m ide.app
```

## Opción Docker

> En macOS el puerto 5000 suele estar ocupado por AirPlay Receiver; por eso el
> IDE usa 8080 por defecto (configurable con `PORT`).

La imagen ya trae Java 17; el jar de MARS se descarga en el host (queda en
`tools/`, que se monta en `/app`).

```bash
make mars                 # en el host: tools/Mars4_5.jar
docker build --rm . -t csp-image
docker run --rm -ti -p 8080:8080 -e PORT=8080 -v "$(pwd)":/app csp-image
# dentro del contenedor (el repo está montado en /app):
antlr -Dlanguage=Python3 -visitor -no-listener -Xexact-output-dir -o compiscript/generated program/Compiscript.g4
python3 Driver.py program/program.cps
python3 Driver.py examples/mips/05_strings.cps --simulate   # MIPS en MARS
python3 -m pytest -q
python3 -m ide.app        # abrir http://localhost:8080 en el navegador del host
```

## MARS 4.5

Instalar Java (macOS: `brew install openjdk`; Ubuntu: `sudo apt install
default-jre`; Windows: Temurin 17+) y descargar el simulador:

```bash
java -version          # 17 o más reciente
make mars              # curl -> tools/Mars4_5.jar
```

Otra ubicación del jar: variable `MARS_JAR=/ruta/Mars4_5.jar`.

El compilador corre MARS **sin interfaz gráfica** (y con la JVM en modo
headless, así no aparece ninguna ventana ni ícono):

```bash
java -Djava.awt.headless=true -jar tools/Mars4_5.jar nc ae2 se3 sm 1000000 programa.asm
```

| Argumento | Significado |
|---|---|
| `nc` | sin aviso de copyright |
| `ae2` / `se3` | código de salida 2 si no ensambla, 3 si falla la simulación |
| `sm` | empieza en la etiqueta `main` |
| `1000000` | límite de instrucciones (un bucle infinito termina ahí) |

### Abrir el `.asm` en la GUI de MARS

Para ver registros y memoria paso a paso:

1. `python3 Driver.py examples/mips/01_recursion.cps --out fact.asm`
   (o **⬇ Descargar .asm** en el IDE).
2. `java -jar tools/Mars4_5.jar` (sin argumentos abre la GUI).
3. *File → Open* → `fact.asm`; *Settings*: activar **Initialize Program
   Counter to global 'main' if defined**.
4. *Run → Assemble* (F3) y *Run → Go* (F5) o *Step* (F7). La salida sale en
   la consola *Run I/O*; los registros en el panel de la derecha.

## Driver (línea de comandos)

```
python3 Driver.py <archivo.cps> [--tac] [--out ARCHIVO] [--runtime] [--run]
                                [--mips] [--regalloc linear|stack] [--simulate] [--steps N]
                                [--symbols] [--tree] [--lisp] [--dot salida.dot] [--quiet]
```

El Driver compila con las dos pasadas (`compile_file`). Si hay errores
sintácticos o semánticos los reporta y **no genera TAC ni MIPS**: las
opciones `--tac`, `--out`, `--runtime`, `--run`, `--mips` y `--simulate` no
hacen nada y el código de salida es 1.

| Opción | Efecto |
|---|---|
| (ninguna) | Reporta errores sintácticos y semánticos con línea:columna y, si no hay, cuántas instrucciones de TAC se generaron. |
| `--tac` | Imprime el código intermedio numerado. |
| `--out X.tac` | Guarda el código intermedio numerado en `X.tac`. |
| `--out X.asm` | Si el archivo termina en `.asm`, guarda el **MIPS** (listo para MARS). |
| `--mips` | Imprime el código MIPS32. |
| `--regalloc linear\|stack` | Asignación de registros del MIPS: `linear` (linear scan, por defecto) o `stack` (todo temporal en la pila). |
| `--simulate` | Genera el MIPS, lo ejecuta en MARS y muestra la salida y el código de salida. |
| `--steps N` | Límite de instrucciones en MARS con `--simulate` (por defecto 1 000 000). |
| `--runtime` | Imprime el área global, los registros de activación (encabezado por uso, parámetros, locales y temporales) y el layout de cada clase con su vtable. |
| `--run` | Ejecuta el TAC con el intérprete (`compiscript/ir/interp.py`) e imprime la salida del programa. |
| `--symbols` | Imprime la tabla de símbolos (entorno, nombre, categoría, tipo, línea, tamaño, dirección, etiqueta). |
| `--tree` | Árbol sintáctico indentado con la posición de cada token. |
| `--lisp` | Árbol en notación `(regla hijo ...)` de ANTLR. |
| `--dot X.dot` | Exporta el árbol a Graphviz; si `dot` está instalado también genera `X.svg`. |
| `--quiet` | Omite el resumen final. |

Código de salida: `0` sin errores, `1` con errores de compilación (o un error
en tiempo de ejecución con `--run`/`--simulate`, un bucle que agota los pasos
de MARS, o MARS no disponible), `2` uso incorrecto (p. ej. archivo
inexistente o un `--regalloc` desconocido).

Ejemplos:

```
$ python3 Driver.py examples/02_funciones_y_closures.cps --tac --quiet
 1  func_begin main, 4
 2      param "Mundo"
 3      t1 = call saludar, 1
 4      print t1
...
17  func_begin factorial, 20
18      t1 = n
19      if t1 > 1 goto L1
20      return 1
21  L1:
...

$ python3 Driver.py examples/02_funciones_y_closures.cps --run --quiet
Hola Mundo
120
2
4

$ python3 Driver.py examples/02_funciones_y_closures.cps --runtime --quiet
...
Registro de activación crearContador_siguiente (nivel 2, static link -> crearContador) frame_size = 12
  fp[+4]         static link -> crearContador (4 B)
  fp[+0]         control link (fp anterior) (4 B)
  fp[-4]         temporal t1 (4 B)

$ python3 Driver.py examples/mips/01_recursion.cps --mips --quiet
...
fact:                                   # func_begin fact, 20
        addiu $sp, $sp, -8
        sw $ra, 4($sp)                  # dirección de retorno
        sw $fp, 0($sp)                  # control link
        move $fp, $sp
        addiu $sp, $sp, -4              # locales 0 B, spill 0, $s 1
        sw $s0, -4($fp)                 # callee-saved
...

$ python3 Driver.py examples/mips/01_recursion.cps --simulate --regalloc stack --quiet
fact(10) = 3628800
fib(15) = 610
esPar(7) = false
mcd(84, 36) = 12
(MARS terminó con código 0)

$ python3 Driver.py examples/mips/08_try_catch.cps --simulate --quiet
...
antes del error sin try
Error en tiempo de ejecución: división entre cero
(MARS terminó con código 1)

$ python3 Driver.py examples/err_02_ambitos.cps --tac
[Error semántico] línea 2:6 — la variable 'noExiste' no ha sido declarada
...
✘ 5 error(es) encontrado(s); no se generó código intermedio
```

Con `make`: `make run F=archivo.cps` equivale a `python3 Driver.py archivo.cps`.

### Desde Python

```python
from compiscript.codegen import compile_file
from compiscript.ir.interp import run

res = compile_file("examples/03_clases_y_herencia.cps")
if res.ok:
    print(res.program.format())            # TAC numerado
    print(res.table.format_runtime())      # registros de activación y clases
    print(run(res.program, res.table))     # salida del programa
else:
    for e in res.errors:
        print(e)
```

MIPS y MARS:

```python
from compiscript.codegen import compile_file
from compiscript.mips.simulator import run_mars

res = compile_file("examples/mips/05_strings.cps", regalloc="linear")   # o "stack"
asm = res.asm                      # None si hubo errores
out = run_mars(asm)                # MarsResult(stdout, exit_code, timeout, error)
print(out.stdout, out.exit_code)
```

## IDE

1. `make ide` (o `python3 -m ide.app`) y abrir <http://localhost:8080>.
2. Escribir código en el editor; el análisis y la generación de TAC corren en
   vivo (o con **Compilar** / `Ctrl+Enter`).
3. Pestañas:
   * **Errores**: sintácticos y semánticos; clic para saltar a la línea.
   * **Código intermedio**: el TAC numerado. Si el programa tiene errores queda
     vacío ("no se generó código intermedio").
   * **MIPS**: el `.asm` con resaltado (instrucciones, registros, etiquetas y
     directivas), el número de instrucciones y el modo de registros. El botón
     **⬇ Descargar .asm** guarda `programa.asm`. Si el programa tiene errores
     queda vacío.
   * **Registros de activación**: un cuadro por función con su nivel, static
     link, `frame_size`, el encabezado (cada campo con el motivo por el que se
     incluye) y el contenido del marco; después, el layout de cada clase con
     sus atributos, la vtable y el constructor.
   * **Salida**: lo que imprime el programa al ejecutar el TAC con el botón
     **⚙ Ejecutar TAC**, o lo que imprime el `.asm` en MARS con **▶ Ejecutar
     en MARS** (con el código de salida de MARS). Un error en ejecución sin
     `try` se muestra en rojo.
   * **Tabla de símbolos** y **Árbol sintáctico** (colapsable, con el tipo de
     cada expresión).
4. **Ejemplos…** carga los programas de `examples/` y `program/`.
5. El selector **registros: linear scan / solo pila** cambia el modo de
   asignación de registros del MIPS (pestaña y ejecución en MARS).
6. **Árbol SVG** abre el árbol dibujado con Graphviz (requiere `dot` en el servidor).

El código se conserva en el navegador entre recargas (`localStorage`).

API usada por el IDE (JSON, `{"source": "..."}` en el cuerpo):

| Endpoint | Respuesta |
|---|---|
| `POST /api/analyze` | `ok`, `errors`, `symbols` (filas), `scopes`, `tree` |
| `POST /api/compile` (`regalloc` opcional) | `ok`, `errors`, `tac` (líneas), `symbols` (`globals_size`, `activation_records`, `classes`, `symbols`), `mips` (líneas del `.asm`), `regalloc`, `mips_error` |
| `POST /api/run` | `ok`, `errors`, `output` (líneas impresas), `runtime_error` |
| `POST /api/run` con `"engine": "mars"` (`regalloc` opcional) | `ok`, `errors`, `stdout`, `output`, `exit_code`, `timeout`, `runtime_error`, `error` |

MARS debe estar disponible en el servidor (Java + `tools/Mars4_5.jar`); si no,
`/api/run` con `engine: "mars"` responde `exit_code: null` y el motivo en
`error`.

## Tests

```bash
make test            # o: .venv/bin/python -m pytest -q
pytest tests/test_classes.py -v      # un grupo de reglas semánticas
pytest tests/ir tests/tac -v         # código intermedio
pytest tests/mips -v                 # MIPS (traducción, registros, runtime, MARS)
pytest tests/mips/test_e2e.py -v     # extremo a extremo en MARS contra el intérprete
MARS_JAR=/no/existe pytest -q        # todo menos lo que necesita MARS
```

| Carpeta | Qué prueba |
|---|---|
| `tests/test_*.py` | Análisis semántico, un archivo por grupo de reglas, y `test_examples` (los `examples/NN_*.cps` compilan y los `err_*.cps` fallan en las líneas comentadas). |
| `tests/ir/` | Cuádruplos, temporales, vida y linear scan, errores en ejecución, registros de activación, contrato del generador e intérprete con TAC escrito a mano. |
| `tests/tac/` | Driver (`--tac`, `--out`, `--runtime`, `--run`), IDE (`/api/compile`, `/api/run`) y pruebas de extremo a extremo: programa → TAC → intérprete → salida esperada. |
| `tests/mips/` | Traducción de cada instrucción, `getReg()` y modos, llamadas, memoria, runtime y excepciones (`test_runtime_lib.py`), Driver e IDE (`test_driver_ide.py`) y extremo a extremo (`test_e2e.py`): programa → TAC → MIPS → MARS, comparado con el intérprete en los modos `linear` y `stack`, más casos fallidos (error de compilación, error en ejecución sin `try`, bucle infinito). |

Las pruebas que ejecutan MARS se saltan si no hay Java o `tools/Mars4_5.jar`.

El mapa requisito → archivo → tests → demo está en
[RUBRICA_MIPS.md](RUBRICA_MIPS.md) (Proyecto 3) y
[RUBRICA_TAC.md](RUBRICA_TAC.md) (Proyecto 2).
