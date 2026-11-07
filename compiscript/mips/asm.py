"""Programa MIPS32 en construcción: segmento `.data`, segmento `.text` y rutinas
del runtime.

    asm = MipsProgram()
    msg = asm.string("hola")             # .asciiz internado -> "__str_1"
    asm.label("main")
    asm.emit("la", "$a0", msg, comment="print \"hola\"")
    print(asm.text())

Las etiquetas del TAC (`L3`, `fact`, `Perro_hablar`) se usan tal cual; las que
crea el compilador empiezan con `__` (`__str_1`, `__globals`, `__raise`) para
no chocar con identificadores del programa fuente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

INDENT = " " * 8
WORD_DIRECTIVES = {".word", ".space", ".float"}


def escape_asciiz(text: str) -> str:
    """Escapa un string para `.asciiz` (MARS acepta \\n, \\t, \\" y \\\\)."""
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t"))


@dataclass
class DataItem:
    label: str
    directive: str
    values: Tuple[str, ...]
    comment: str = ""


class MipsProgram:
    def __init__(self):
        self._data: List[DataItem] = []
        self._labels: set = set()
        self._text: List[str] = []
        self._routines: Dict[str, str] = {}
        self._strings: Dict[str, str] = {}
        self._floats: Dict[float, str] = {}
        self._counter = 0

    # ------------------------------------------------------------------ .data

    def data(self, label: str, directive: str, *values, comment: str = "") -> str:
        """Agrega un dato con etiqueta (una sola vez por etiqueta)."""
        if label not in self._labels:
            self._labels.add(label)
            self._data.append(DataItem(label, directive, tuple(str(v) for v in values), comment))
        return label

    def has_data(self, label: str) -> bool:
        return label in self._labels

    def string(self, text: str) -> str:
        """Etiqueta de un literal string en `.data` (se interna: un literal repetido
        comparte etiqueta)."""
        label = self._strings.get(text)
        if label is None:
            label = self._strings[text] = self.unique("__str")
            self.data(label, ".asciiz", f'"{escape_asciiz(text)}"')
        return label

    def float_const(self, value: float) -> str:
        """Etiqueta de una constante float de precisión simple en `.data`."""
        label = self._floats.get(value)
        if label is None:
            label = self._floats[value] = self.unique("__flt")
            self.data(label, ".float", repr(float(value)))
        return label

    def unique(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    # ------------------------------------------------------------------ .text

    def emit(self, op: str, *args, comment: str = "") -> None:
        line = INDENT + op + (" " + ", ".join(str(a) for a in args) if args else "")
        if comment:
            line = f"{line:<40}# {comment}"
        self._text.append(line)

    def label(self, name: str, comment: str = "") -> None:
        self._text.append(f"{name}:" + (f"{' ' * max(1, 39 - len(name))}# {comment}" if comment else ""))

    def comment(self, text: str) -> None:
        self._text.append(f"{INDENT}# {text}")

    def blank(self) -> None:
        self._text.append("")

    # ---------------------------------------------------------------- runtime

    def add_routine(self, name: str, code: str) -> None:
        """Rutina del runtime (código MIPS ya escrito). Se agrega una sola vez,
        al final del segmento de texto."""
        self._routines.setdefault(name, code.strip("\n"))

    def replace_routine(self, name: str, code: str) -> None:
        self._routines[name] = code.strip("\n")

    def has_routine(self, name: str) -> bool:
        return name in self._routines

    # ---------------------------------------------------------------- salida

    def text_lines(self) -> List[str]:
        return list(self._text)

    def lines(self) -> List[str]:
        out = ["# Código MIPS32 generado por el compilador de Compiscript",
               "# Ejecutar con MARS 4.5: java -jar Mars4_5.jar nc sm programa.asm", ""]
        out.append(f"{INDENT}.data")
        for item in self._data:
            if item.directive in WORD_DIRECTIVES:
                out.append(f"{INDENT}.align 2")
            line = f"{item.label}: {item.directive} {', '.join(item.values)}"
            out.append(f"{line:<40}# {item.comment}" if item.comment else line)
        out += ["", f"{INDENT}.text", f"{INDENT}.globl main"]
        out += self._text
        for name, code in self._routines.items():
            out += ["", f"# ---- runtime: {name}", code]
        return out

    def text(self) -> str:
        return "\n".join(self.lines()) + "\n"

    def __str__(self) -> str:
        return self.text()

    # ------------------------------------------------------------ consultas

    def instructions(self) -> List[Tuple[str, Sequence[str]]]:
        """(mnemónico, operandos) de cada instrucción del segmento de texto
        (sin etiquetas ni comentarios). Útil en los tests."""
        out = []
        for line in self._text:
            code = line.split("#", 1)[0].strip()
            if not code or code.endswith(":"):
                continue
            op, _, rest = code.partition(" ")
            out.append((op, tuple(a.strip() for a in rest.split(",")) if rest else ()))
        return out

    def find(self, op: str) -> List[Sequence[str]]:
        return [args for o, args in self.instructions() if o == op]


__all__ = ["MipsProgram", "escape_asciiz"]
