"""Integración del MIPS con el Driver (CLI) y el IDE (Flask).

Las pruebas que ejecutan MARS se saltan si no hay Java o `tools/Mars4_5.jar`.
"""

import os

import pytest

import Driver
from compiscript.mips.simulator import mars_available

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALIDO = os.path.join(ROOT, "examples", "02_funciones_y_closures.cps")
CON_ERRORES = os.path.join(ROOT, "examples", "err_01_tipos.cps")

requires_mars = pytest.mark.skipif(not mars_available(),
                                   reason="MARS no disponible: correr `make mars` (requiere Java)")

PROGRAMA = """
function fact(n: integer): integer { if (n <= 1) { return 1; } return n * fact(n - 1); }
print("fact(5) = " + fact(5));
"""


@pytest.fixture
def fuente(tmp_path):
    def escribir(texto, nombre="prog.cps"):
        path = tmp_path / nombre
        path.write_text(texto, encoding="utf-8")
        return str(path)
    return escribir


# ---------------------------------------------------------------------------
# Driver.py
# ---------------------------------------------------------------------------

def test_driver_mips_imprime_el_asm(fuente, capsys):
    assert Driver.main([fuente(PROGRAMA), "--mips", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert ".data" in out and ".text" in out and "main:" in out and "fact:" in out
    assert "jal fact" in out and "jal __concat" in out


def test_driver_out_asm_guarda_el_mips(fuente, tmp_path, capsys):
    destino = tmp_path / "prog.asm"
    assert Driver.main([fuente(PROGRAMA), "--out", str(destino), "--quiet"]) == 0
    texto = destino.read_text(encoding="utf-8")
    assert texto.startswith("# Código MIPS32") and "main:" in texto
    assert "MIPS guardado" in capsys.readouterr().out


def test_driver_out_sin_asm_sigue_guardando_tac(fuente, tmp_path):
    destino = tmp_path / "prog.tac"
    assert Driver.main([fuente(PROGRAMA), "--out", str(destino), "--quiet"]) == 0
    assert "func_begin fact" in destino.read_text(encoding="utf-8")


def test_driver_regalloc_cambia_el_codigo(fuente, tmp_path):
    src = fuente(PROGRAMA)
    lin, stk = tmp_path / "lin.asm", tmp_path / "stk.asm"
    assert Driver.main([src, "--out", str(lin), "--regalloc", "linear", "--quiet"]) == 0
    assert Driver.main([src, "--out", str(stk), "--regalloc", "stack", "--quiet"]) == 0
    lin, stk = lin.read_text(encoding="utf-8"), stk.read_text(encoding="utf-8")
    assert lin != stk and lin.count("($fp)") < stk.count("($fp)")


def test_driver_regalloc_invalido(fuente):
    with pytest.raises(SystemExit) as exc:
        Driver.main([fuente(PROGRAMA), "--regalloc", "registros"])
    assert exc.value.code == 2


def test_driver_con_error_semantico_no_genera_asm(tmp_path, capsys):
    destino = tmp_path / "no.asm"
    assert Driver.main([CON_ERRORES, "--mips", "--out", str(destino), "--simulate"]) == 1
    out = capsys.readouterr().out
    assert "[Error semántico]" in out
    assert ".text" not in out and "MARS" not in out
    assert "no se generó código intermedio ni MIPS" in out
    assert not destino.exists()


def test_driver_simulate_sin_mars(fuente, capsys, monkeypatch):
    monkeypatch.setenv("MARS_JAR", "/no/existe/Mars4_5.jar")
    assert Driver.main([fuente(PROGRAMA), "--simulate", "--quiet"]) == 1
    assert "make mars" in capsys.readouterr().out


@requires_mars
@pytest.mark.parametrize("modo", ["linear", "stack"])
def test_driver_simulate_muestra_la_salida(fuente, capsys, modo):
    assert Driver.main([fuente(PROGRAMA), "--simulate", "--regalloc", modo, "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "fact(5) = 120" in out and "código 0" in out


@requires_mars
def test_driver_simulate_error_en_ejecucion_sale_con_1(fuente, capsys):
    assert Driver.main([fuente('print("a"); print(1 / 0);'), "--simulate", "--quiet"]) == 1
    out = capsys.readouterr().out
    assert "a\nError en tiempo de ejecución: división entre cero" in out and "código 1" in out


@requires_mars
def test_driver_simulate_bucle_infinito(fuente, capsys):
    assert Driver.main([fuente("while (true) { }"), "--simulate", "--steps", "5000", "--quiet"]) == 1
    assert "límite de 5000" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# IDE: /api/compile con MIPS y /api/run en MARS
# ---------------------------------------------------------------------------

from ide.app import app   # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_compile_incluye_mips(client):
    data = client.post("/api/compile", json={"source": PROGRAMA}).get_json()
    assert data["ok"] is True and data["regalloc"] == "linear" and data["mips_error"] is None
    mips = "\n".join(data["mips"])
    assert ".text" in mips and "main:" in mips and "fact:" in mips and "jal __concat" in mips


def test_api_compile_respeta_el_modo_de_registros(client):
    lin = client.post("/api/compile", json={"source": PROGRAMA, "regalloc": "linear"}).get_json()
    stk = client.post("/api/compile", json={"source": PROGRAMA, "regalloc": "stack"}).get_json()
    assert stk["regalloc"] == "stack" and lin["mips"] != stk["mips"]
    assert client.post("/api/compile", json={"source": PROGRAMA, "regalloc": "x"}).get_json()["regalloc"] == "linear"


def test_api_compile_con_errores_mips_vacio(client):
    data = client.post("/api/compile", json={"source": 'let x: integer = "a";'}).get_json()
    assert data["ok"] is False and data["mips"] == [] and data["tac"] == []


def test_api_run_mars_con_errores_no_ejecuta(client):
    data = client.post("/api/run", json={"source": "print(y);", "engine": "mars"}).get_json()
    assert data["ok"] is False and data["exit_code"] is None and data["errors"]


def test_api_run_mars_sin_mars(client, monkeypatch):
    monkeypatch.setenv("MARS_JAR", "/no/existe/Mars4_5.jar")
    data = client.post("/api/run", json={"source": PROGRAMA, "engine": "mars"}).get_json()
    assert data["ok"] is True and data["exit_code"] is None and "make mars" in data["error"]


def test_api_run_sin_engine_sigue_usando_el_interprete(client):
    data = client.post("/api/run", json={"source": PROGRAMA}).get_json()
    assert data == {"ok": True, "errors": [], "output": ["fact(5) = 120"], "runtime_error": None}


@requires_mars
@pytest.mark.parametrize("modo", ["linear", "stack"])
def test_api_run_mars_ejecuta(client, modo):
    data = client.post("/api/run", json={"source": PROGRAMA, "engine": "mars", "regalloc": modo}).get_json()
    assert data["exit_code"] == 0 and data["output"] == ["fact(5) = 120"] and data["regalloc"] == modo


@requires_mars
def test_api_run_mars_error_en_ejecucion(client):
    src = 'print("a"); let xs: integer[] = [1]; print(xs[4]);'
    data = client.post("/api/run", json={"source": src, "engine": "mars"}).get_json()
    assert data["output"] == ["a"] and data["exit_code"] == 1
    assert data["runtime_error"] == "Error en tiempo de ejecución: índice fuera de rango"


def test_index_tiene_pestana_mips_y_botones(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-tab="mips"' in html and 'id="download"' in html
    assert 'id="mars"' in html and 'id="regalloc"' in html
    js = client.get("/static/app.js").get_data(as_text=True)
    assert "engine: \"mars\"" in js and "programa.asm" in js
