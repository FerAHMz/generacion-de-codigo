// Recursión simple, mutua y de cola.
function fact(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * fact(n - 1);
}

function fib(n: integer): integer {
  if (n < 2) { return n; }
  return fib(n - 1) + fib(n - 2);
}

function esPar(n: integer): boolean {
  if (n == 0) { return true; }
  return esImpar(n - 1);
}

function esImpar(n: integer): boolean {
  if (n == 0) { return false; }
  return esPar(n - 1);
}

function mcd(a: integer, b: integer): integer {
  if (b == 0) { return a; }
  return mcd(b, a % b);
}

print("fact(10) = " + fact(10));
print("fib(15) = " + fib(15));
print("esPar(7) = " + esPar(7));
print("mcd(84, 36) = " + mcd(84, 36));
