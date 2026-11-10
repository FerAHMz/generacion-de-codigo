// switch con fallthrough, break y default.
function nombreDia(d: integer): string {
  let r: string = "";
  switch (d) {
    case 1: r = "lunes"; break;
    case 2: r = "martes"; break;
    case 6:
    case 7: r = "fin de semana"; break;
    default: r = "otro";
  }
  return r;
}
for (let d: integer = 1; d <= 7; d = d + 1) { print(d + ": " + nombreDia(d)); }

let n: integer = 2;
switch (n) {
  case 1: print("uno");
  case 2: print("dos");
  case 3: print("tres");
  default: print("default");
}
