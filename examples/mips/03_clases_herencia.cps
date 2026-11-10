// Clases, constructores, herencia y despacho dinámico.
class Figura {
  let nombre: string;
  function constructor(nombre: string) { this.nombre = nombre; }
  function area(): integer { return 0; }
  function describir(): string { return this.nombre + " con área " + this.area(); }
}

class Rectangulo : Figura {
  let ancho: integer;
  let alto: integer;
  function constructor(ancho: integer, alto: integer) {
    this.nombre = "rectángulo";
    this.ancho = ancho;
    this.alto = alto;
  }
  function area(): integer { return this.ancho * this.alto; }
}

class Cuadrado : Rectangulo {
  function constructor(lado: integer) {
    this.nombre = "cuadrado";
    this.ancho = lado;
    this.alto = lado;
  }
}

let figuras: Figura[] = [new Figura("punto"), new Rectangulo(3, 4), new Cuadrado(5)];
foreach (f in figuras) {
  print(f.describir());
}
let total: integer = 0;
for (let i: integer = 0; i < 3; i = i + 1) { total = total + figuras[i].area(); }
print("total = " + total);
