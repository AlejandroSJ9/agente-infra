from agente.evaluar_recepcionista import argumentos_correctos, esperado, normalizar_red, percentil
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
