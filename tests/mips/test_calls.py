"""Secuencias de llamada y retorno: argumentos, static link, registros
guardados alrededor de `jal`, prólogo/epílogo y balance de $sp."""

import pytest

from compiscript.ir.tac import Op
from compiscript.mips.regs import RegisterManager

from .helpers import MODES, compile_ok, requires_mars, run_asm, run_source, translator_class

NESTED = """
function a(p: integer): integer {
  let x: integer = p;
  function b(k: integer): integer {
    function c(): integer {
      x = x + 10;
      if (x < 40) { return b(k + 1); }
      return x + k;
    }
    return c();
  }
  return b(0);
}
print(a(1));
"""

FLAGS = """
function f(a: boolean, b: boolean, c: integer): integer {
  if (a) { if (b) { return c; } }
  return 0 - c;
}
print(f(true, true, 7));
print(f(true, false, 7));
"""

METHODS = """
class Animal {
  function hablar(n: integer): integer { return n; }
}
class Perro : Animal {
  function hablar(n: integer): integer { return n * 2; }
}
let a: Animal = new Perro();
print(a.hablar(21));
"""


def partial(src, label, mode="linear", **pools):
    """Traduce solo el cuerpo de `label` (sin prólogo ni epílogo)."""
    res = compile_ok(src)
    tr = translator_class()(res.program, res.table, mode)
    if pools:
        tr.regs = RegisterManager(tr, res.program, res.table, mode, **pools)
    lo, hi = tr.functions[label]
    tr.function, tr.record = label, res.table.record_of(label)
    tr.regs.enter_function(label, lo, hi, tr.record)
    tr.frame = tr.frame_layout(label, tr.record)
    for pos in range(lo + 1, hi):
        q = res.program[pos]
        if q.op != Op.RETURN:
            tr.translate_quad(q, pos)
    return res, tr


def calls_in(tr):
    return [(o, a) for o, a in tr.asm.instructions() if o in ("jal", "jalr")]


# ------------------------------------------------------------- argumentos

def test_arguments_go_to_their_offsets_and_area_is_released():
    _, tr = partial("function s(a: integer, b: integer): integer { return a + b; }\nprint(s(1, 2));",
                    "main")
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("s",)))
    assert ("addiu", ("$sp", "$sp", "-8")) in ins[:j]
    stores = [args for o, args in ins[:j] if o == "sw"]
    assert [a[1] for a in stores] == ["0($sp)", "4($sp)"]
    assert ins[j + 1] == ("addiu", ("$sp", "$sp", "8"))


def test_boolean_arguments_use_one_byte_like_the_record():
    res, tr = partial(FLAGS, "main")
    rec = res.table.record_of("f")
    offs = [p.frame_offset - rec.params_base for p in rec.params]
    assert offs == [0, 1, 4]
    ins = tr.asm.instructions()
    first_call = ins.index(("jal", ("f",)))
    arg_stores = [(o, a[1]) for o, a in ins[:first_call] if o in ("sb", "sw")]
    assert arg_stores == [("sb", "0($sp)"), ("sb", "1($sp)"), ("sw", "4($sp)")]


def test_result_is_copied_from_v0():
    _, tr = partial("function u(): integer { return 3; }\nprint(u());", "main")
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("u",)))
    assert ins[j + 1][0] == "move" and ins[j + 1][1][1] == "$v0"


def test_float_result_is_copied_from_f0():
    _, tr = partial("function u(): float { return 1.5; }\nprint(u());", "main")
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("u",)))
    assert ins[j + 1][0] == "mov.s" and ins[j + 1][1][1] == "$f0"


# ------------------------------------------------------------ static link

def test_static_link_pushed_only_when_callee_needs_it():
    res = compile_ok(NESTED)
    assert not res.table.record_of("a").needs_static_link
    assert res.table.record_of("a_b").needs_static_link
    _, tr = partial(NESTED, "main")
    assert not any("static link" in ln for ln in tr.asm.text_lines())
    _, tr = partial(NESTED, "a")
    text = "\n".join(tr.asm.text_lines())
    assert "sw $fp, 0($sp)" in text and "static link de a_b" in text


def test_static_link_follows_p_minus_q_plus_one_links():
    res, tr = partial(NESTED, "a_b_c")
    c, b = res.table.record_of("a_b_c"), res.table.record_of("a_b")
    # c (nivel 3) llama a b (nivel 2): se siguen 3 - 2 + 1 = 2 enlaces.
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("a_b",)))
    chain = [a for o, a in ins[:j] if o == "lw" and a[0] == "$v1"][-2:]
    assert chain == [("$v1", f"{c.header_offset('static_link')}($fp)"),
                     ("$v1", f"{b.header_offset('static_link')}($v1)")]
    assert ins[j - 1] == ("sw", ("$v1", "0($sp)"))


# ----------------------------------------------- registros alrededor de jal

def test_t_registers_alive_across_call_are_saved_and_restored():
    src = "function g(): integer { return 5; }\nlet y: integer = 2;\nprint(y * 3 + g());"
    _, tr = partial(src, "main", int_pool=("$t0", "$t1"))
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("g",)))
    saved = [a[0] for o, a in ins[:j] if o == "sw" and a[1].endswith("($sp)")]
    restored = [a[0] for o, a in ins[j:] if o == "lw" and a[1].endswith("($sp)")]
    assert saved and saved == restored and all(r.startswith("$t") for r in saved)


def test_values_in_s_registers_are_not_saved_by_the_caller():
    src = "function g(): integer { return 5; }\nlet y: integer = 2;\nprint(y * 3 + g());"
    _, tr = partial(src, "main")
    ins = tr.asm.instructions()
    j = ins.index(("jal", ("g",)))
    assert not [a for o, a in ins[:j] if o == "sw" and a[1].endswith("($sp)")]
    assert any(r.startswith("$s") for o, a in ins[:j] for r in a)


def test_stack_mode_saves_nothing_around_calls():
    src = "function g(): integer { return 5; }\nlet y: integer = 2;\nprint(y * 3 + g());"
    _, tr = partial(src, "main", mode="stack")
    assert "guardar registros" not in tr.asm.text()


# --------------------------------------------------------------- métodos

def test_virtual_call_uses_jalr_and_the_method_record():
    res = compile_ok(METHODS)
    tr = translator_class()(res.program, res.table)
    tr.function = "main"
    call = next(i for i, q in enumerate(res.program) if q.op == Op.CALL and not hasattr(q.arg1, "name"))
    rec = tr.callee_record(call)
    assert rec is not None and rec.label == "Animal_hablar"


def test_virtual_call_emits_jalr_with_the_method_address():
    res = compile_ok(METHODS)
    tr = translator_class()(res.program, res.table)
    lo, hi = tr.functions["main"]
    tr.function, tr.record = "main", res.table.main
    tr.regs.enter_function("main", lo, hi, res.table.main)
    call = next(i for i, q in enumerate(res.program) if q.op == Op.CALL and not hasattr(q.arg1, "name"))
    first = call
    while res.program[first - 1].op == Op.PARAM:
        first -= 1
    for pos in range(first, call + 1):
        tr.translate_quad(res.program[pos], pos)
    ins = tr.asm.instructions()
    assert [o for o, _ in ins].count("jalr") == 1
    assert ("addiu", ("$sp", "$sp", "-8")) in ins     # this + n


# ------------------------------------------------------- prólogo / epílogo

def full(src, mode="linear", **pools):
    res = compile_ok(src)
    tr = translator_class()(res.program, res.table, mode)
    if pools:
        tr.regs = RegisterManager(tr, res.program, res.table, mode, **pools)
    return res, tr.translate()


def block(prog, label):
    lines = prog.text_lines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{label}:"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == ""), len(lines))
    return "\n".join(lines[start:end])


def test_prologue_saves_ra_only_in_non_leaf_functions():
    res, prog = full(NESTED)
    a = block(prog, "a")          # llama a b: guarda $ra en el encabezado
    c = block(prog, "a_b_c")      # llama a b: también
    assert "sw $ra, 4($sp)" in a and "sw $ra, 4($sp)" in c
    leaf = block(full("function k(): integer { return 1; }\nprint(k());")[1], "k")
    assert "$ra" not in leaf.replace("jr $ra", "")
    assert "sw $fp, 0($sp)" in leaf and "move $fp, $sp" in leaf


def test_leaf_that_calls_the_runtime_saves_ra_in_its_frame():
    src = "function k(): integer { print(1); return 1; }\nprint(k());"
    res, prog = full(src)
    assert not res.table.record_of("k").needs_return_address
    k = block(prog, "k")
    assert "$ra (llama al runtime)" in k and "lw $ra" in k


def test_epilogue_restores_s_registers_saved_in_prologue():
    src = FACT_SRC
    res, prog = full(src)
    f = block(prog, "fact")
    saved = [ln.split()[1].rstrip(",") for ln in f.splitlines() if "callee-saved" in ln]
    assert saved and all(f"lw {r}," in f for r in saved)


def test_return_jumps_to_the_epilogue_unless_it_is_last():
    _, prog = full(FACT_SRC)
    f = block(prog, "fact")
    assert f.count("j __ret_fact") == 1          # el return del caso base
    assert "__ret_fact:" in "\n".join(prog.text_lines())


FACT_SRC = """
function fact(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * fact(n - 1);
}
print(fact(10));
"""

PROGRAMS = {
    "factorial": FACT_SRC,
    "fibonacci": """
function fib(n: integer): integer {
  if (n < 2) { return n; }
  return fib(n - 1) + fib(n - 2);
}
print(fib(15));
print(fib(10) + fib(8) * fib(5));
""",
    "recursion_mutua": """
function esPar(n: integer): boolean {
  if (n == 0) { return true; }
  return esImpar(n - 1);
}
function esImpar(n: integer): boolean {
  if (n == 0) { return false; }
  return esPar(n - 1);
}
print(esPar(10));
print(esImpar(7));
print(esPar(7));
""",
    "closure_modifica_capturada": NESTED,
    "contador": """
function crear(): integer {
  let cuenta: integer = 0;
  function siguiente(): integer { cuenta = cuenta + 1; return cuenta; }
  siguiente(); siguiente();
  return siguiente();
}
print(crear());
""",
    "argumentos_boolean": FLAGS,
    "argumentos_float": """
function elegir(a: float, b: float, primero: boolean): float {
  if (primero) { return a; }
  return b;
}
print(elegir(2.5, 0.75, true));
print(elegir(2.5, 0.75, false));
""",
    "valores_vivos_en_llamadas": """
function g(x: integer): integer { return x + 1; }
let y: integer = 2;
print(y * 3 + g(y) * (y + g(g(y))));
""",
    "recursion_profunda": """
function suma(n: integer): integer {
  if (n == 0) { return 0; }
  return n + suma(n - 1);
}
print(suma(2000));
""",
    "funcion_hoja_que_imprime": """
function k(n: integer): integer { print(n); return n + 1; }
print(k(k(1)));
""",
    "muchos_argumentos": """
function m(a: integer, b: integer, c: integer, d: integer, e: integer, f: integer): integer {
  return a - b + c - d + e - f;
}
print(m(10, 1, 20, 2, 30, 3));
""",
}


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_programs_with_calls_match_the_interpreter(name, mode):
    run, expected = run_source(PROGRAMS[name], mode)
    assert run.exit_code == 0
    assert run.lines == expected


@requires_mars
@pytest.mark.parametrize("name", ["fibonacci", "valores_vivos_en_llamadas", "closure_modifica_capturada"])
def test_same_output_with_only_two_t_registers(name):
    res, prog = full(PROGRAMS[name], int_pool=("$t0", "$t1"), float_pool=("$f4",))
    from compiscript.ir.interp import run as interp_run
    assert run_asm(prog.text()).lines == interp_run(res.program, res.table)


@requires_mars
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_stack_and_frame_pointer_are_balanced(name, mode):
    _, prog = full(PROGRAMS[name], mode)
    text = prog.text()
    main = block(prog, "main").splitlines()
    reserve = 0
    if len(main) > 2 and main[2].strip().startswith("addiu $sp, $sp, -"):
        reserve = -int(main[2].split(",")[2].split("#")[0])
    # Sin restaurar $sp desde $fp al terminar: $sp debe quedar donde lo dejó el prólogo de main.
    text = text.replace("        move $sp, $fp\n        li $v0, 10", "        li $v0, 10")
    run = run_asm(text, registers=["$sp", "$fp"])
    assert run.registers["$fp"] == 0x7FFFEFFC
    assert run.registers["$sp"] == 0x7FFFEFFC - reserve
