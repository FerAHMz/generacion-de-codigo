// try/catch: errores dentro de funciones, try anidado y error sin capturar.
function dividir(a: integer, b: integer): integer { return a / b; }
function promedio(xs: integer[], n: integer): integer {
  let s: integer = 0;
  for (let i: integer = 0; i < n; i = i + 1) { s = s + xs[i]; }
  return dividir(s, n);
}

let datos: integer[] = [4, 8, 12];
try { print("promedio = " + promedio(datos, 3)); } catch (e) { print("no"); }
try { print(promedio(datos, 0)); } catch (e) { print("error: " + e); }
try { print(promedio(datos, 5)); } catch (e) { print("error: " + e); }

class Nodo { let valor: integer; let siguiente: Nodo; }
let lista: Nodo = new Nodo();
lista.valor = 1;
try {
  try { print(lista.siguiente.valor); }
  catch (interno) { print("interno: " + interno); print(datos[3]); }
} catch (externo) { print("externo: " + externo); }

print("antes del error sin try");
print(dividir(1, 0));
print("no se imprime");
