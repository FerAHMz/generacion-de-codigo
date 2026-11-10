// Concatenación de strings con conversión de integer, float, boolean y null.
let nombre: string = "Ada";
let edad: integer = 36;
let activa: boolean = edad > 18;
let nada: string = null;
print("Hola, " + nombre + "!");
print(nombre + " tiene " + edad + " años");
print("activa: " + activa + ", nada: " + nada);
print("negativo: " + (0 - 2147483647 - 1));
let s: string = "";
for (let i: integer = 0; i < 5; i = i + 1) { s = s + i + ","; }
print(s);
if (nombre == "Ada") { print("igualdad de strings: ok"); }
function repetir(t: string, k: integer): string {
  let r: string = "";
  while (k > 0) { r = r + t; k = k - 1; }
  return r;
}
print(repetir("ab", 3));
