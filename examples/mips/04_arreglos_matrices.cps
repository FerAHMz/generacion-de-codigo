// Arreglos, matrices y algoritmos sobre ellos.
let xs: integer[] = [5, 3, 8, 1, 9, 2];
let n: integer = 6;
// burbuja
for (let i: integer = 0; i < n - 1; i = i + 1) {
  for (let j: integer = 0; j < n - 1 - i; j = j + 1) {
    if (xs[j] > xs[j + 1]) {
      let tmp: integer = xs[j];
      xs[j] = xs[j + 1];
      xs[j + 1] = tmp;
    }
  }
}
let linea: string = "";
foreach (x in xs) { linea = linea + x + " "; }
print(linea);

let m: integer[][] = [[1, 2, 3], [4, 5, 6], [7, 8, 9]];
let traza: integer = 0;
for (let i: integer = 0; i < 3; i = i + 1) { traza = traza + m[i][i]; }
print("traza = " + traza);
m[1][2] = 60;
let suma: integer = 0;
foreach (fila in m) { foreach (v in fila) { suma = suma + v; } }
print("suma = " + suma);

function maximo(a: integer[]): integer {
  let mejor: integer = a[0];
  foreach (v in a) { if (v > mejor) { mejor = v; } }
  return mejor;
}
print("máximo = " + maximo(xs));
