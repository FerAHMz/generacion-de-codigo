// Floats de precisión simple con valores exactos en binario.
let a: float = 2.25;
let b: float = 0.5;
print(a + b);
print(a * b);
print(a / b);
print(a - 4);
let xs: float[] = [1.5, 2.5, 3.25];
let suma: float = 0;
foreach (x in xs) { suma = suma + x; }
print(suma);
print("mitad = " + suma / 2.0);
function cuadrado(x: float): float { return x * x; }
print("cuadrado(1.5) = " + cuadrado(1.5));
if (a > 2) { print("a > 2"); }
