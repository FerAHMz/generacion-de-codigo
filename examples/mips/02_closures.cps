// Funciones anidadas que leen y modifican variables del entorno que las contiene.
function contador(inicio: integer): integer {
  let cuenta: integer = inicio;
  function sumar(k: integer): integer {
    cuenta = cuenta + k;
    return cuenta;
  }
  sumar(2);
  sumar(3);
  return sumar(5);
}

function externa(x: integer): integer {
  function media(y: integer): integer {
    function interna(z: integer): integer {
      return x * 100 + y * 10 + z;
    }
    return interna(y + 1);
  }
  return media(x + 1);
}

print(contador(10));
print(externa(1));
print(externa(3));
