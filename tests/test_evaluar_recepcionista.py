from agente.evaluar_recepcionista import (argumentos_correctos, argumentos_equivalentes, esperado, normalizar_red,
                                         percentil, red_canonica)
from agente.recepcionista import Decision


def test_esperado_y_argumentos():
    fila = {"tipo": "calculadora", "funcion": "vlsm", "red": "10.0.0.0/24", "cantidad": "", "hosts": "50|20", "nube": ""}
    e = esperado(fila)
    assert e["hosts"] == [50, 20] and e["cantidad"] is None
    assert argumentos_correctos(Decision(tipo="calculadora", origen="x", funcion="vlsm", red="10.0.0.0 / 24",
                                         hosts=[50, 20]), e)
    assert not argumentos_correctos(Decision(tipo="calculadora", origen="x", funcion="vlsm", red="10.0.0.0/24",
                                             hosts=[20, 50]), e)


def test_normalizar_y_percentil():
    assert normalizar_red(" 10.0.0.0  255.255.255.0 ") == "10.0.0.0 255.255.255.0"
    assert percentil([1, 2, 3, 4, 100], 0.5) == 3 and percentil([1, 2, 3, 4, 100], 0.95) == 100


def test_red_canonica_y_equivalencia():
    assert red_canonica("10.20.30.0 255.255.255.192") == red_canonica("10.20.30.0/26") == "10.20.30.0/26"
    e = esperado({"tipo": "calculadora", "funcion": "vlsm", "red": "10.0.0.0/24", "cantidad": "",
                  "hosts": "60|25", "nube": ""})
    d = Decision(tipo="calculadora", origen="x", funcion="vlsm", red="10.0.0.0 255.255.255.0", cantidad=3,
                 hosts=[60, 25])
    assert not argumentos_correctos(d, e)          # estricto: la máscara escrita distinto y cantidad sobrante
    assert argumentos_equivalentes(d, e)           # semántico: misma red y la cantidad no la usa VLSM
