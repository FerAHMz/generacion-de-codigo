"""Punto de entrada por línea de comandos.

    python3 Driver.py program.cps                 # compila: reporta errores (y genera TAC si no hay)
    python3 Driver.py program.cps --tac           # imprime el TAC numerado
    python3 Driver.py program.cps --out prog.tac  # guarda el TAC en un archivo
    python3 Driver.py program.cps --runtime       # registros de activación y layout de clases
    python3 Driver.py program.cps --run           # ejecuta el TAC con el intérprete
    python3 Driver.py program.cps --symbols       # además imprime la tabla de símbolos
    python3 Driver.py program.cps --tree          # imprime el árbol sintáctico indentado
    python3 Driver.py program.cps --lisp          # árbol en notación (rule ...) de ANTLR
    python3 Driver.py program.cps --dot out.dot   # exporta el árbol a Graphviz (y SVG si hay `dot`)

Proyecto 3 (MIPS):

    python3 Driver.py program.cps --mips                 # imprime el .asm
    python3 Driver.py program.cps --out prog.asm         # guarda el .asm (extensión .asm)
    python3 Driver.py program.cps --regalloc stack       # asignación de registros: linear (defecto) | stack
    python3 Driver.py program.cps --simulate             # ejecuta el .asm en MARS y muestra la salida

`--out` guarda MIPS si el archivo termina en `.asm` y TAC en otro caso.

Si hay errores sintácticos o semánticos no se genera TAC ni MIPS (ni se
imprime, guarda o ejecuta). Código de salida: 0 sin errores, 1 con errores (de
compilación, en ejecución con --run/--simulate, o MARS no disponible), 2 uso
incorrecto.
"""

import argparse
import sys

from compiscript.codegen import compile_file
from compiscript.ir.interp import Interpreter, InterpreterError
from compiscript.mips import MODES, MipsNotImplemented
from compiscript.mips.simulator import MarsUnavailable, run_mars
from compiscript.tree_viz import render_dot, tree_to_dot, tree_to_lisp, tree_to_text


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="Driver.py",
                                 description="Compilador de Compiscript a TAC y MIPS32 (MARS)")
    ap.add_argument("file", help="archivo fuente .cps")
    ap.add_argument("--tac", action="store_true", help="imprime el código intermedio (TAC) numerado")
    ap.add_argument("--out", metavar="ARCHIVO",
                    help="guarda el código generado: MIPS si termina en .asm, TAC en otro caso")
    ap.add_argument("--runtime", action="store_true",
                    help="imprime los registros de activación y el layout de las clases")
    ap.add_argument("--run", action="store_true", help="ejecuta el TAC con el intérprete")
    ap.add_argument("--symbols", action="store_true", help="imprime la tabla de símbolos")
    ap.add_argument("--tree", action="store_true", help="imprime el árbol sintáctico indentado")
    ap.add_argument("--lisp", action="store_true", help="imprime el árbol en notación LISP de ANTLR")
    ap.add_argument("--dot", metavar="ARCHIVO", help="exporta el árbol a un archivo Graphviz .dot")
    ap.add_argument("--mips", action="store_true", help="imprime el código MIPS (.asm)")
    ap.add_argument("--regalloc", choices=sorted(MODES), default="linear",
                    help="asignación de registros del MIPS (por defecto: linear)")
    ap.add_argument("--simulate", action="store_true", help="ejecuta el MIPS en MARS y muestra la salida")
    ap.add_argument("--steps", type=int, default=1_000_000, metavar="N",
                    help="límite de instrucciones en MARS con --simulate (por defecto 1000000)")
    ap.add_argument("--quiet", action="store_true", help="no imprime el resumen final")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = compile_file(args.file, regalloc=args.regalloc)
    except OSError as exc:
        print(f"No se pudo leer '{args.file}': {exc}")
        return 2
    analysis = result.analysis

    if args.tree:
        print(tree_to_text(analysis.tree))
    if args.lisp:
        print(tree_to_lisp(analysis.tree, analysis.parse.parser))
    if args.dot:
        dot = tree_to_dot(analysis.tree, analysis.node_types)
        with open(args.dot, "w", encoding="utf-8") as fh:
            fh.write(dot)
        svg = args.dot.rsplit(".", 1)[0] + ".svg"
        if render_dot(dot, svg):
            print(f"Árbol exportado a {args.dot} y {svg}")
        else:
            print(f"Árbol exportado a {args.dot} (instale Graphviz para generar la imagen)")
    if args.symbols:
        print(result.table)
        print()

    for err in result.errors:
        print(err)

    status = 0 if result.ok else 1
    if result.ok:
        if args.tac:
            print(result.program.format())
            print()
        if args.out and not args.out.lower().endswith(".asm"):
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(result.program.format() + "\n")
            print(f"TAC guardado en {args.out}")
        if args.runtime:
            print(result.table.format_runtime())
            print()
        if args.run:
            interp = Interpreter(result.program, result.table, on_print=print)
            try:
                interp.run()
            except InterpreterError as exc:
                print(f"Error del intérprete: {exc}")
                status = 1
            if interp.error is not None:
                status = 1
            print()
        wants_asm = args.mips or args.simulate or (args.out or "").lower().endswith(".asm")
        if wants_asm:
            status = max(status, mips_outputs(result, args))

    if not args.quiet:
        n = len(result.errors)
        if n:
            print(f"✘ {n} error(es) encontrado(s); no se generó código intermedio ni MIPS")
        else:
            print(f"✔ Sin errores ({len(result.program)} instrucciones de TAC)")
    return status


def mips_outputs(result, args) -> int:
    """--mips, --out x.asm y --simulate. Devuelve el código de salida."""
    try:
        asm = result.asm
    except MipsNotImplemented as exc:
        print(f"No se pudo generar MIPS: {exc}")
        return 1
    if args.mips:
        print(asm)
    if args.out and args.out.lower().endswith(".asm"):
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(asm)
        print(f"MIPS guardado en {args.out} (modo {args.regalloc})")
    if args.simulate:
        try:
            run = run_mars(asm, steps=args.steps)
        except MarsUnavailable as exc:
            print(exc)
            return 1
        if run.stdout:
            print(run.stdout)
        if run.timeout:
            print(f"MARS: se alcanzó el límite de {args.steps} instrucciones")
        if run.error:
            print(f"MARS: {run.error}")
        print(f"(MARS terminó con código {run.exit_code})")
        return 0 if run.ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
