"""Segmento de datos y acceso a variables: globales, locales, parámetros y
variables de funciones externas (static links)."""

import pytest

from compiscript.ir.tac import Var
from compiscript.mips import MipsTranslator
from compiscript.mips.memory import AddressError, GLOBALS_LABEL, parse_address
from compiscript.types import BOOLEAN, FLOAT, INTEGER

from .helpers import MODES, compile_ok, requires_mars, run_source, translate

NESTED = """
function a(p: integer): integer {
  let x: integer = p;
  function b(): integer {
    function c(): integer { x = x + 10; return x; }
    return c() + c();
  }
  return b();
}
print(a(1));
"""


@pytest.mark.parametrize("address, expected", [
    ("global[0]", ("global", 0)), ("global[12]", ("global", 12)),
    ("fp[+8]", ("fp", 8)), ("fp[-4]", ("fp", -4)),
])
def test_parse_address(address, expected):
    assert parse_address(address) == expected


def test_parse_address_rejects_unknown():
    with pytest.raises(AddressError):
        parse_address("this[+4]")


def _translator(src, label):
    res = compile_ok(src)
    tr = MipsTranslator(res.program, res.table)
    tr.record = res.table.record_of(label)
    return tr


def test_globals_area_in_data_segment():
    res, prog = translate("let a: integer = 1; let b: boolean = true; let c: integer = 2;")
    size = res.table.globals_size
    assert f"{GLOBALS_LABEL}: .space {size}" in prog.text()


def test_width_by_type():
    tr = _translator("", "main")
    tr.load_var(Var("b", "global[4]", 0, BOOLEAN), "$t8")
    tr.load_var(Var("f", "global[8]", 0, FLOAT), "$f30")
    tr.store_var("$t8", Var("i", "global[0]", 0, INTEGER))
    tr.store_var("$t8", Var("b", "global[4]", 0, BOOLEAN))
    assert tr.asm.instructions() == [
        ("lb", ("$t8", f"{GLOBALS_LABEL}+4")), ("l.s", ("$f30", f"{GLOBALS_LABEL}+8")),
        ("sw", ("$t8", GLOBALS_LABEL)), ("sb", ("$t8", f"{GLOBALS_LABEL}+4")),
    ]


def test_local_and_param_relative_to_fp():
    tr = _translator(NESTED, "a")
    tr.load_var(Var("p", "fp[+8]", 0, INTEGER), "$t8")
    tr.store_var("$t8", Var("x", "fp[-4]", 0, INTEGER))
    assert tr.asm.instructions() == [("lw", ("$t8", "8($fp)")), ("sw", ("$t8", "-4($fp)"))]


def test_nonlocal_follows_static_links_of_each_frame():
    res = compile_ok(NESTED)
    c, b = res.table.record_of("a_b_c"), res.table.record_of("a_b")
    tr = _translator(NESTED, "a_b_c")
    tr.load_var(Var("x", "fp[-4]", 2, INTEGER), "$t8")
    assert tr.asm.instructions() == [
        ("lw", ("$v1", f"{c.header_offset('static_link')}($fp)")),
        ("lw", ("$v1", f"{b.header_offset('static_link')}($v1)")),
        ("lw", ("$t8", "-4($v1)")),
    ]


def test_missing_static_link_is_an_error():
    tr = _translator(NESTED, "a")
    with pytest.raises(AddressError):
        tr.load_var(Var("x", "fp[-4]", 1, INTEGER), "$t8")


@requires_mars
@pytest.mark.parametrize("mode", MODES[:1])
def test_globals_of_every_type_in_mars(mode):
    src = """
    let i: integer = 41;
    let b: boolean = false;
    let f: float = 2.5;
    let s: string = "texto";
    i = i + 1;
    b = true;
    print(i); print(b); print(f); print(s);
    """
    run, expected = run_source(src, mode)
    assert run.lines == expected == ["42", "true", "2.5", "texto"]
