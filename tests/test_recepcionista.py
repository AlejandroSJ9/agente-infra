"""Pruebas de las reglas del recepcionista y de su respaldo (sin API)."""

import pytest

from agente.recepcionista import Decision, decidir, decidir_por_reglas, extraer_red, validar_salida


@pytest.mark.parametrize("pregunta, funcion, red, extra", [
    ("Analiza 192.168.1.10/24", "analizar_red", "192.168.1.10/24", {}),
    ("192.168.1.0 255.255.255.0 cuántos hosts", "analizar_red", "192.168.1.0 255.255.255.0", {}),
    ("10.0.0.0 con máscara 255.255.252.0", "analizar_red", "10.0.0.0 255.255.252.0", {}),
    ("divide 172.31.0.0/16 en 6 subredes en mi VPC de AWS", "dividir_en_subredes", "172.31.0.0/16",
     {"cantidad": 6, "nube": "aws"}),
    ("haz vlsm de 10.0.0.0/24 para 50, 20 y 10 hosts", "vlsm", "10.0.0.0/24", {"hosts": [50, 20, 10]}),
    ("necesito 3 subredes de 192.168.0.0/24 con 100, 50 y 20 equipos", "vlsm", "192.168.0.0/24",
     {"hosts": [100, 50, 20]}),
    ("¿la IP 8.8.8.8 es pública?", "analizar_red", "8.8.8.8/32", {}),
])
def test_reglas_de_calculadora(pregunta, funcion, red, extra):
    d = decidir_por_reglas(pregunta)
    assert d.tipo == "calculadora" and d.origen == "regla"
    assert d.funcion == funcion and d.red == red
    for campo, valor in extra.items():
        assert getattr(d, campo) == valor


@pytest.mark.parametrize("pregunta", ["hola", "Hola!!", "gracias", "buenas tardes", "chao"])
def test_saludos(pregunta):
    assert decidir_por_reglas(pregunta).tipo == "directa"


@pytest.mark.parametrize("pregunta", ["¿Qué es el teorema CAP?", "instalé 10.0.0.5 ayer", "hola, ¿qué es PACELC?"])
def test_sin_regla_va_al_modelo(pregunta):
    assert decidir_por_reglas(pregunta) is None


def test_extraer_red_no_confunde_dos_ips():
    assert extraer_red("de 10.0.0.1 a 10.0.0.5") is None       # 10.0.0.5 no es una máscara válida


class ClienteFalso:
    def __init__(self, decision=None, error=None):
        self.decision, self.error = decision, error

    def clasificar(self, pregunta):
        if self.error:
            raise self.error
        return self.decision


def test_respaldo_si_la_api_falla():
    d = decidir("¿Qué es CAP?", ClienteFalso(error=TimeoutError("sin red")))
    assert d.tipo == "biblioteca" and d.origen == "respaldo" and "TimeoutError" in d.extra["error"]


def test_respaldo_sin_cliente():
    assert decidir("¿Qué es CAP?", None).tipo == "biblioteca"


def test_confianza_baja_va_a_biblioteca():
    d = decidir("algo raro", ClienteFalso(Decision(tipo="fuera_de_tema", origen="modelo:x", confianza=0.3)))
    assert d.tipo == "biblioteca" and d.extra["tipo_original"] == "fuera_de_tema"


def test_las_reglas_van_antes_que_el_modelo():
    cliente = ClienteFalso(error=AssertionError("no debía llamarse"))
    assert decidir("analiza 10.0.0.0/8", cliente).origen == "regla"


@pytest.mark.parametrize("malo", [
    {"tipo": "otro", "funcion": None, "confianza": 0.9, "hosts": None},
    {"tipo": "calculadora", "funcion": "sumar", "confianza": 0.9, "hosts": None},
    {"tipo": "biblioteca", "funcion": None, "confianza": 1.7, "hosts": None},
    {"tipo": "calculadora", "funcion": "vlsm", "confianza": 0.9, "hosts": ["diez"]},
])
def test_valida_la_salida_del_modelo(malo):
    with pytest.raises(ValueError):
        validar_salida(malo)
