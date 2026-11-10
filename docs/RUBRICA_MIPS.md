# Cumplimiento de la rúbrica — Proyecto 3 (generación de código MIPS)

Mapa de cada requisito de `README_CODE_GENERATION.md` del curso al código que
lo implementa, a los tests que lo validan y a cómo mostrarlo en la
presentación. Toda la batería corre con `make test`; las pruebas que ejecutan
MARS se saltan si no hay Java o `tools/Mars4_5.jar` (`make mars`).

Convenciones:

* `mips/x::test` = `tests/mips/test_x.py::test`.
* `e2e[...]` = `tests/mips/test_e2e.py`: programa → TAC → MIPS → MARS, comparado
  con el intérprete de TAC (`ir/interp.run`) en los modos `linear` y `stack`.
* *Demo*: **CLI** = `python3 Driver.py <archivo> <opciones>`; **IDE** = cargar
  el ejemplo desde *Ejemplos…*, abrir la pestaña **MIPS** y pulsar
  **▶ Ejecutar en MARS**.

| Componente | Puntos |
|---|---|
| 1. Secuencias de llamada y retorno | 20 |
| 2. Asignación de registros (`getReg()`) | 20 |
| 3. Código MIPS funcional y simulado en MARS | 60 |

## 1. Secuencias de llamada y retorno (20 pts)

| Requisito | Dónde | Tests | Demo |
|---|---|---|---|
| Paso de argumentos en los offsets del registro de activación (boolean de 1 byte) y liberación del área | `mips/calls.py` (`op_param`, `op_call`), `docs/MIPS.md` §1.2 | `mips/calls::test_arguments_go_to_their_offsets_and_area_is_released`, `test_boolean_arguments_use_one_byte_like_the_record` | **CLI** `examples/mips/01_recursion.cps --mips` |
| Valor de retorno en `$v0` / `$f0` | `calls.py` (`op_return`, `op_call`) | `mips/calls::test_result_is_copied_from_v0`, `test_float_result_is_copied_from_f0` | `06_floats.cps` |
| Prólogo y epílogo: control link, `$ra` solo si no es hoja, `$s` callee-saved | `calls.py` (`op_func_begin`, `op_func_end`), MIPS.md §1.3 | `mips/calls::test_prologue_saves_ra_only_in_non_leaf_functions`, `test_leaf_that_calls_the_runtime_saves_ra_in_its_frame`, `test_epilogue_restores_s_registers_saved_in_prologue`, `test_return_jumps_to_the_epilogue_unless_it_is_last` | pestaña **MIPS** de `01_recursion.cps` |
| Static link para funciones anidadas (p − q + 1 enlaces) y acceso a variables no locales | `calls.py`, `mips/memory.py` | `mips/calls::test_static_link_pushed_only_when_callee_needs_it`, `test_static_link_follows_p_minus_q_plus_one_links`; `mips/memory::test_nonlocal_follows_static_links_of_each_frame`, `test_missing_static_link_is_an_error` | `02_closures.cps` |
| Registros guardados alrededor de `jal` (`$t` vivos, nada en modo pila) | `calls.py` (`live_across`) | `mips/calls::test_t_registers_alive_across_call_are_saved_and_restored`, `test_values_in_s_registers_are_not_saved_by_the_caller`, `test_stack_mode_saves_nothing_around_calls` | — |
| Llamadas virtuales (`jalr` a la dirección de la vtable) | `calls.py`, `mips/objects.py` | `mips/calls::test_virtual_call_uses_jalr_and_the_method_record`, `test_virtual_call_emits_jalr_with_the_method_address` | `03_clases_herencia.cps` |
| El estado de la memoria se conserva: `$sp`/`$fp` balanceados, recursión y recursión mutua | `calls.py` | `mips/calls::test_stack_and_frame_pointer_are_balanced`, `test_programs_with_calls_match_the_interpreter`; `e2e::test_caso[recursion_profunda]`, `e2e::test_ejemplo_igual_al_interprete[examples/mips/01_recursion.cps]` | `01_recursion.cps` en MARS |
| Excepciones que cruzan llamadas: `__raise` restaura `$fp`/`$sp` del `try` | `mips/exceptions.py`, MIPS.md §7 | `mips/runtime_lib::test_raise_restaura_fp_y_sp_y_salta_al_catch`, `test_try_catch_en_mars[error_en_funcion_llamada]`, `[catch_en_funcion_recursiva]` | `08_try_catch.cps` |

## 2. Asignación de registros: `getReg()` (20 pts)

| Requisito | Dónde | Tests | Demo |
|---|---|---|---|
| `getReg()` con linear scan sobre intervalos de vida | `mips/regs.py`, `ir/liveness.py`, MIPS.md §2.2 | `mips/regs::test_scan_reuses_register_when_intervals_only_touch`, `test_scan_spills_the_interval_that_ends_last`, `test_no_two_live_values_share_a_register`, `test_no_conflicts_with_two_registers` | **IDE** selector *registros: linear scan* |
| Clases de registro: `$t` (caller-saved), `$s` para valores vivos durante una llamada, `$f` para float | `regs.py` | `mips/regs::test_scan_prefers_s_registers_across_calls`, `test_value_alive_across_call_goes_to_s_register`, `test_scan_falls_back_to_other_class_when_preferred_is_full`, `test_float_and_int_classes_are_separate`, `test_scratch_registers_are_not_allocatable`, `test_main_does_not_save_s_registers` | pestaña **MIPS** |
| Spill a memoria cuando no hay registros, sin cambiar la salida | `regs.py` | `mips/regs::test_small_pool_produces_spill_slots`, `test_spilled_values_keep_the_same_output`; `mips/calls::test_same_output_with_only_two_t_registers` | — |
| Opción de usar solo la pila | `regs.py` (modo `stack`), MIPS.md §2.3 | `mips/translator_base::test_stack_mode_loads_temp_from_its_slot`, `test_stack_mode_def_goes_to_scratch_and_is_stored`; `mips/modes::test_modes_available`, `test_unknown_mode_is_rejected` | **CLI** `--regalloc stack`; **IDE** *registros: solo pila* |
| Los dos modos dan la misma salida; linear usa menos accesos a memoria | `regs.py` | `mips/modes::test_both_modes_give_the_interpreter_output`, `test_linear_uses_fewer_memory_accesses_than_stack`; todos los `e2e` corren en `linear` y `stack`; `mips/driver_ide::test_driver_regalloc_cambia_el_codigo`, `test_api_compile_respeta_el_modo_de_registros` | comparar `--regalloc linear` y `stack` |
| Las rutinas del runtime no pisan registros con temporales | `mips/runtime_lib.py` (convención) | `mips/runtime_lib::test_rutinas_solo_pisan_registros_permitidos` | — |

## 3. Código MIPS funcional y simulado en MARS (60 pts)

### 3.1 Traducción de cada instrucción

| Construcción | Dónde | Tests del `.asm` | Tests en MARS | Demo |
|---|---|---|---|---|
| Aritmética entera y float, `int_to_float`, `not`, copias | `mips/arith.py` | `mips/tr_arith::test_integer_ops_mnemonics`, `test_float_ops_mnemonics`, `test_float_constants_come_from_data`, `test_int_to_float_uses_mtc1_and_cvt`, `test_not_uses_xori` | `mips/tr_arith::test_integer_arithmetic_matches_interpreter`, `test_float_arithmetic_matches_interpreter`, `test_copies_and_not`; `e2e::test_caso[floats_exactos]` | `06_floats.cps` |
| División y módulo con revisión de cero | `arith.py` | `mips/tr_arith::test_integer_division_uses_div_and_mflo_after_zero_check`, `test_modulo_uses_mfhi`, `test_division_has_no_check_for_other_ops` | `mips/tr_arith::test_division_by_zero_without_try_prints_the_message`, `test_division_by_zero_with_variable_divisor`; `e2e::test_error_en_ejecucion_sin_try[division_entre_cero]` | — |
| Relacionales, saltos, `if`/`while`/`for`/`switch`, corto circuito | `mips/control.py` | `mips/tr_control::test_integer_relational_with_value`, `test_float_relational_with_value`, `test_float_greater_swaps_operands`, `test_conditional_jumps`, `test_float_conditional_jump` | `mips/tr_control::test_control_programs_match_interpreter`, `test_switch_fallthrough_output`, `test_float_relationals_output`; `e2e[examples/mips/07_switch.cps]` | `07_switch.cps` |
| `print` por tipo | `control.py` | `mips/tr_control::test_print_syscalls_by_type` | `mips/translator_base::test_print_constant_runs_in_mars` | — |
| Arreglos y matrices con revisión de null e índice | `mips/data_structs.py` | `mips/tr_arrays::test_alloc_uses_sbrk_and_stores_length`, `test_index_get_checks_null_and_bounds_before_lw`, `test_index_set_checks_before_sw`, `test_float_elements_use_l_s_and_s_s`, `test_len_checks_null` | `mips/tr_arrays::test_array_programs_match_interpreter`, `test_matrix_output`, `test_out_of_bounds_stops_with_the_message`, `test_null_array_access_is_an_error`; `e2e[examples/mips/04_arreglos_matrices.cps]` | `04_arreglos_matrices.cps` |
| Clases, herencia, vtables y despacho dinámico | `mips/objects.py` | `mips/tr_objects::test_vtables_in_data_follow_class_layout`, `test_new_reserves_object_size_and_stores_vtable`, `test_method_loads_vtable_and_slot_after_null_check`, `test_boolean_field_uses_byte_access_and_float_field_uses_l_s` | `mips/tr_objects::test_dynamic_dispatch_and_fields`, `test_override_in_grandchild_and_super_methods`, `test_object_fields_holding_objects`, `test_field_of_null_is_an_error`; `e2e[examples/mips/03_clases_herencia.cps]` | `03_clases_herencia.cps` |
| Strings: `concat` con conversión de integer, float, boolean y null | `mips/runtime_lib.py` (`__concat`, `__itoa`, `__ftoa`, `__btoa`, `op_concat`) | `mips/runtime_lib::test_concat_traduce_con_jal_a_las_rutinas`, `test_rutinas_solo_pisan_registros_permitidos` | `mips/runtime_lib::test_itoa`, `test_ftoa_igual_que_la_syscall_2`, `test_btoa`, `test_concat_y_null`, `test_alloc_alinea_a_4`, `test_concat_en_programas`; `e2e::test_caso[strings_con_todos_los_tipos]`, `e2e[examples/mips/05_strings.cps]` | `05_strings.cps` |
| `try/catch`: pila de manejadores y `__raise` | `mips/exceptions.py` | `mips/runtime_lib::test_push_handler_guarda_l_fp_y_sp`, `test_raise_restaura_fp_y_sp_y_salta_al_catch` | `mips/runtime_lib::test_try_catch_en_mars` (6 programas: error en función llamada, anidados, sin error, recursión, `break` dentro de `try`); `e2e::test_caso[try_catch_desde_funcion]`, `e2e[examples/mips/08_try_catch.cps]` | `08_try_catch.cps` |

### 3.2 Simulación en MARS y batería de casos exitosos y fallidos

| Requisito | Dónde | Tests | Demo |
|---|---|---|---|
| Ejecutar el `.asm` en un simulador (MARS 4.5 sin GUI) | `mips/simulator.py` (`run_mars`) | `mips/runtime_lib::test_comando_sin_gui_y_headless`, `test_limpia_el_ruido_de_mars`, `test_imprime_42`, `test_codigo_de_salida_con_syscall_17`, `test_error_de_ensamblado`, `test_mars_imprime_los_acentos_de_los_mensajes` | **CLI** `--simulate` |
| **Casos exitosos**: cada ejemplo da en MARS la misma salida que el intérprete, en los dos modos | `tests/mips/test_e2e.py` | `e2e::test_ejemplo_igual_al_interprete` (`examples/NN_*.cps`, `examples/mips/*.cps`, `program/program.cps`), `e2e::test_caso` (8 programas por tema), `e2e::test_ejemplo_genera_asm_en_ambos_modos` | **IDE** *Ejecutar TAC* vs *Ejecutar en MARS* |
| **Fallido — error de compilación**: no se genera `.asm` | `codegen/__init__.py` (`asm is None`), `Driver.py` | `e2e::test_error_de_compilacion_no_genera_asm` (`examples/err_*.cps`), `e2e::test_error_sintactico_o_semantico_no_genera_asm`; `mips/driver_ide::test_driver_con_error_semantico_no_genera_asm`, `test_api_compile_con_errores_mips_vacio`, `test_api_run_mars_con_errores_no_ejecuta` | **CLI** `examples/err_01_tipos.cps --mips` (código 1) |
| **Fallido — error en ejecución sin `try`**: imprime el mensaje y termina con código ≠ 0 | `exceptions.py` (`__raise_uncaught`, syscall 17) | `e2e::test_error_en_ejecucion_sin_try` (división entre cero, índice fuera de rango, índice negativo, null, error dentro de funciones); `mips/runtime_lib::test_try_catch_en_mars[sin_try_termina_con_mensaje]`; `mips/driver_ide::test_driver_simulate_error_en_ejecucion_sale_con_1`, `test_api_run_mars_error_en_ejecucion` | final de `08_try_catch.cps` |
| **Fallido — bucle infinito**: termina por el límite de pasos | `simulator.py` (`sm N`, `timeout`) | `e2e::test_bucle_infinito_termina_por_limite_de_pasos`; `mips/runtime_lib::test_bucle_infinito_termina_por_limite_de_pasos`; `mips/driver_ide::test_driver_simulate_bucle_infinito` | **CLI** `--simulate --steps 5000` |

## 4. IDE, CLI y documentación (requisitos sin puntaje propio)

| Requisito | Dónde | Tests |
|---|---|---|
| IDE: pestaña **MIPS** con resaltado, **Descargar .asm**, **Ejecutar en MARS**, selector de modo de registros | `ide/app.py` (`/api/compile` con `mips`, `/api/run` con `engine: "mars"`), `ide/static/` | `mips/driver_ide::test_api_compile_incluye_mips`, `test_api_compile_respeta_el_modo_de_registros`, `test_api_run_mars_ejecuta`, `test_api_run_sin_engine_sigue_usando_el_interprete`, `test_index_tiene_pestana_mips_y_botones` |
| CLI: `--mips`, `--out x.asm`, `--regalloc`, `--simulate` | `Driver.py` | `mips/driver_ide::test_driver_mips_imprime_el_asm`, `test_driver_out_asm_guarda_el_mips`, `test_driver_out_sin_asm_sigue_guardando_tac`, `test_driver_regalloc_invalido`, `test_driver_simulate_muestra_la_salida`, `test_driver_simulate_sin_mars` |
| Documentación de arquitectura | [ARQUITECTURA.md](ARQUITECTURA.md) §Tercera pasada, [MIPS.md](MIPS.md) | — |
| Documentación de ejecución | [EJECUCION.md](EJECUCION.md) §MARS, §Driver, §IDE | — |

## Guion sugerido para la demo

1. `make test` (toda la batería, 0 skips con MARS instalado).
2. **CLI**: `python3 Driver.py examples/mips/01_recursion.cps --mips | less` —
   prólogo/epílogo de `fact`, `jal`, `$s0` vivo durante la llamada.
3. **CLI**: `--simulate --regalloc linear` y `--regalloc stack` sobre el mismo
   archivo: misma salida, distinto `.asm` (`--out lin.asm` / `--out stk.asm`).
4. **IDE**: cargar `03_clases_herencia.cps` → pestaña **MIPS** (vtables en
   `.data`, `jalr`) → **Ejecutar en MARS**.
5. **IDE**: `08_try_catch.cps` → errores capturados desde funciones y el error
   final sin `try` (código de salida 1).
6. **Fallidos**: `examples/err_01_tipos.cps --mips` (no hay `.asm`, código 1) y
   un `while (true) { }` con `--simulate --steps 5000`.
7. Abrir el `.asm` de `--out` en la GUI de MARS (ver EJECUCION.md) y ejecutar
   paso a paso.
