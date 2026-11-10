"""Ejecución de programas MIPS en MARS 4.5 desde Python.

    from compiscript.mips.simulator import run_mars, mars_available
    res = run_mars(asm_text)            # MarsResult
    res.stdout      # salida del programa (sin el ruido de MARS)
    res.exit_code   # 0, el código de la syscall 17, 2 (no ensambla) o 3 (error de simulación)
    res.timeout     # True si se agotó el límite de pasos o el tiempo

MARS se corre sin GUI (`nc`, sin aviso de copyright) y con la JVM en modo
headless, así no aparece ninguna ventana ni ícono:

    java -Djava.awt.headless=true -jar tools/Mars4_5.jar nc ae2 se3 sm 1000000 prog.asm

* `sm`: empieza en `main` (no en la primera instrucción de `.text`).
* `ae2` / `se3`: código de salida 2 si no ensambla y 3 si hay un error de
  simulación (dirección inválida, etc.).
* El último argumento numérico es el límite de pasos: un bucle infinito
  termina con `timeout=True` en vez de colgar el proceso.

El jar se busca en `$MARS_JAR` o en `tools/Mars4_5.jar` (`make mars`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STEPS = 1_000_000
DEFAULT_TIMEOUT = 60.0          # segundos de reloj (además del límite de pasos)

ASSEMBLE_ERROR = 2
SIMULATION_ERROR = 3

JAVA_FLAGS = [
    "-Djava.awt.headless=true",       # sin ventana ni ícono en el dock (macOS)
    "-Dapple.awt.UIElement=true",
    "-Dfile.encoding=UTF-8",          # .asciiz con acentos
    "-Dstdout.encoding=UTF-8",
]

_STEP_LIMIT = re.compile(r"^\s*Program terminated when maximum step limit \d+ reached\.?\s*$")
_NOISE = (
    re.compile(r"^\s*-- program is finished running.*--\s*$"),
    re.compile(r"^\s*Program terminated by calling exit\s*$"),
)


def mars_jar() -> Path:
    return Path(os.environ.get("MARS_JAR", ROOT / "tools" / "Mars4_5.jar"))


def mars_available() -> bool:
    """Hay Java y el jar de MARS."""
    return mars_jar().exists() and shutil.which("java") is not None


class MarsUnavailable(RuntimeError):
    """No hay Java o no está `tools/Mars4_5.jar` (correr `make mars`)."""


@dataclass
class MarsResult:
    stdout: str                 # salida del programa
    exit_code: int
    timeout: bool = False
    error: str = ""             # mensaje de MARS si no ensambló o falló la simulación

    @property
    def lines(self) -> List[str]:
        return self.stdout.split("\n") if self.stdout else []

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timeout

    def to_dict(self) -> dict:
        return {"stdout": self.stdout, "exit_code": self.exit_code,
                "timeout": self.timeout, "error": self.error}


def mars_command(path: str, steps: int = DEFAULT_STEPS) -> List[str]:
    return ["java", *JAVA_FLAGS, "-jar", str(mars_jar()), "nc", "ae2", "se3", "sm", str(steps), path]


def clean_output(raw: str):
    """Separa la salida del programa de los mensajes de MARS.
    Devuelve (stdout, timeout, error)."""
    lines = raw.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    timeout = False
    error_lines: List[str] = []
    for i, line in enumerate(lines):
        if _STEP_LIMIT.match(line):
            timeout = True
            break
        # "Error in programa.asm line 3 ..." (ensamblado) o "Error in : Runtime exception ..."
        # La salida del programa usa "Error en tiempo de ejecución", que no choca.
        if line.startswith("Error in ") or line.startswith("Processing terminated due to errors"):
            error_lines = lines[i:]
            break
        if any(p.match(line) for p in _NOISE):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out), timeout, "\n".join(l for l in error_lines if l).strip()


def run_mars(asm: str, steps: int = DEFAULT_STEPS, timeout: Optional[float] = DEFAULT_TIMEOUT,
             stdin: str = "") -> MarsResult:
    """Ensambla y ejecuta `asm` (texto del .asm) en MARS sin GUI."""
    if not mars_available():
        raise MarsUnavailable("MARS no disponible: instalar Java y correr `make mars`")
    with tempfile.TemporaryDirectory(prefix="compiscript-mars-") as tmp:
        path = os.path.join(tmp, "programa.asm")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(asm)
        try:
            proc = subprocess.run(mars_command(path, steps), capture_output=True, input=stdin,
                                  encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stdout, _, _ = clean_output(partial)
            return MarsResult(stdout, -1, timeout=True)
    stdout, limit, error = clean_output(proc.stdout)
    code = proc.returncode
    if code in (ASSEMBLE_ERROR, SIMULATION_ERROR) and not error:
        error = (proc.stdout + proc.stderr).strip()
    return MarsResult(stdout, code, timeout=limit, error=error)


def run_file(path: str, steps: int = DEFAULT_STEPS, timeout: Optional[float] = DEFAULT_TIMEOUT) -> MarsResult:
    with open(path, encoding="utf-8") as fh:
        return run_mars(fh.read(), steps, timeout)


__all__ = ["ASSEMBLE_ERROR", "DEFAULT_STEPS", "MarsResult", "MarsUnavailable", "SIMULATION_ERROR",
           "clean_output", "mars_available", "mars_command", "mars_jar", "run_file", "run_mars"]
