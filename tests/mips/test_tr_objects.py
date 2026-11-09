"""Traducción de objetos: vtables, `new`, `getf`/`setf` y `method` con
despacho dinámico (Felipe Aguilar)."""

import pytest

from compiscript.ir.interp import run as interp_run
from compiscript.mips import MODES
from compiscript.mips.objects import vtable_label

from .helpers import requires_mars, run_asm, translate

ERROR_NULL = "Error en tiempo de ejecución: acceso a una referencia null"

HIERARCHY = """
class Animal {
  let nombre: string;
  let patas: integer = 4;
  let vivo: boolean = true;
  function constructor(nombre: string) { this.nombre = nombre; }
  function hablar(): string { return "..."; }
  function comer(): string { return "come"; }
  function getPatas(): integer { return this.patas; }
}
class Perro : Animal {
  let peso: float = 10.5;
  function hablar(): string { return "guau"; }
}
let a: Animal = new Animal("gato");
let p: Animal = new Perro("toby");
print(a.hablar());
print(p.hablar());
print(p.comer());
print(p.nombre);
p.patas = 3;
print(p.getPatas());
print(a.getPatas());
print(p.vivo);
p.vivo = false;
print(p.vivo);
let q: Perro = new Perro("rex");
print(q.peso);
q.peso = q.peso * 2.0;
print(q.peso);
"""


def mars_matches(src, mode, exit_code=0):
    res, prog = translate(src, mode)
    run = run_asm(prog.text())
    assert run.exit_code == exit_code, run.raw
    assert run.lines == interp_run(res.program, res.table)
    return run.lines


# ------------------------------------------------------------------ texto

def test_vtables_in_data_follow_class_layout():
    res, prog = translate(HIERARCHY)
    text = prog.text()
    for name, layout in res.table.class_layouts.items():
        labels = ", ".join(label for _, label in layout.vtable)
        assert f"{vtable_label(name)}: .word {labels}" in text
    perro = res.table.class_layouts["Perro"]
    assert perro.vtable[perro.method_slot("hablar")][1] == "Perro_hablar"
    assert perro.vtable[perro.method_slot("comer")][1] == "Animal_comer"


def test_class_without_methods_has_a_vtable():
    _, prog = translate("class V { let x: integer = 1; }\nlet v: V = new V();\nprint(v.x);")
    assert f"{vtable_label('V')}: .word 0" in prog.text()


def test_new_reserves_object_size_and_stores_vtable():
    res, prog = translate(HIERARCHY)
    seq = prog.instructions()
    size = res.table.class_layouts["Perro"].object_size
    i = seq.index(("la", ("$v1", vtable_label("Perro"))))
    assert seq[i - 3] == ("li", ("$a0", str(size)))
    assert seq[i - 2] == ("li", ("$v0", "9"))
    assert seq[i + 1] == ("sw", ("$v1", "0($v0)"))


def test_method_loads_vtable_and_slot_after_null_check():
    res, prog = translate(HIERARCHY)
    seq = prog.instructions()
    slot = res.table.class_layouts["Animal"].method_slot("comer")
    k = next(k for k, (o, a) in enumerate(seq) if o == "lw" and a[1] == f"{4 * slot}($v1)"
             and k > 0 and seq[k - 1][0] == "lw" and seq[k - 1][1][0] == "$v1")
    assert seq[k - 1][1][1].startswith("0(")       # lw $v1, 0(obj): vtable
    assert "bnez" in [o for o, _ in seq[k - 6:k - 1]]
    assert "jalr" in [o for o, _ in seq[k:k + 12]]


def test_boolean_field_uses_byte_access_and_float_field_uses_l_s():
    _, prog = translate(HIERARCHY)
    ops = [o for o, _ in prog.instructions()]
    assert "sb" in ops and "lb" in ops and "l.s" in ops and "s.s" in ops


# ------------------------------------------------------------------- MARS

@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_dynamic_dispatch_and_fields(mode):
    out = mars_matches(HIERARCHY, mode)
    assert out == ["...", "guau", "come", "toby", "3", "4", "true", "false", "10.5", "21.0"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_override_in_grandchild_and_super_methods(mode):
    src = """
class A { function f(): integer { return 1; } function g(): integer { return this.f() * 10; } }
class B : A { function f(): integer { return 2; } }
class C : B { function f(): integer { return 3; } }
let xs: A[] = [new A(), new B(), new C()];
foreach (x in xs) { print(x.g()); }
"""
    assert mars_matches(src, mode) == ["10", "20", "30"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_object_fields_holding_objects(mode):
    src = """
class Nodo {
  let valor: integer;
  let sig: Nodo;
  function constructor(v: integer) { this.valor = v; this.sig = null; }
}
let a: Nodo = new Nodo(1);
let b: Nodo = new Nodo(2);
a.sig = b;
print(a.sig.valor);
let n: Nodo = a;
let s = 0;
while (n != null) { s = s + n.valor; n = n.sig; }
print(s);
"""
    assert mars_matches(src, mode) == ["2", "3"]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_field_of_null_is_an_error(mode):
    src = """
class Nodo { let valor: integer = 7; let sig: Nodo; }
let a: Nodo = new Nodo();
print(a.valor);
print(a.sig.valor);
print(0);
"""
    assert mars_matches(src, mode, exit_code=1) == ["7", ERROR_NULL]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_method_on_null_is_an_error(mode):
    src = """
class A { let otro: A; function f(): integer { return 1; } }
let a: A = new A();
print(a.f());
print(a.otro.f());
"""
    assert mars_matches(src, mode, exit_code=1) == ["1", ERROR_NULL]


@requires_mars
@pytest.mark.parametrize("mode", MODES)
def test_set_field_of_null_is_an_error(mode):
    src = """
class A { let x: integer; let otro: A; }
let a: A = new A();
a.otro.x = 5;
"""
    assert mars_matches(src, mode, exit_code=1) == [ERROR_NULL]
