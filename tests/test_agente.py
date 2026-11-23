"""Pruebas del flujo del agente con dobles falsos (sin modelo, sin buscador real, sin API)."""

import json

import pytest

from agente.agente import Agente
from agente.recepcionista import Decision


class BuscadorFalso:
    def buscar(self, pregunta, k):
        return [{"id": "doc:1:0", "cita": "Taller CAP, pág. 1", "texto": "CAP analiza particiones.", "similitud": 0.9,
                 "posicion": 1}]


class LLMFalso:
    def __init__(self, falla=False):
        self.falla, self.mensajes = falla, None

    def completar(self, mensajes, max_tokens=350):
        if self.falla:
            raise ConnectionError("llm caído")
        self.mensajes = mensajes
        return "**La respuesta técnica:** texto del modelo", {"prompt_ms": 100, "prompt_n": 50,
                                                             "predicted_ms": 200, "predicted_n": 20}


class RecepcionistaFalso:
    def __init__(self, tipo):
        self.tipo = tipo

    def clasificar(self, pregunta):
        return Decision(tipo=self.tipo, origen="modelo:falso", confianza=0.95)


@pytest.fixture
def crear(tmp_path):
    def _crear(llm=None, tipo="biblioteca"):
        return Agente(BuscadorFalso(), llm or LLMFalso(), RecepcionistaFalso(tipo), carpeta_trazas=tmp_path)
    return _crear


def leer_trazas(carpeta):
    return [json.loads(l) for f in carpeta.glob("*.jsonl") for l in f.read_text().splitlines()]


def test_biblioteca_usa_fichas_y_deja_traza(crear, tmp_path):
    r = crear().responder("¿Qué es CAP?")
    assert r["texto"].startswith("**La respuesta técnica:**")
    traza = leer_trazas(tmp_path)[0]
    assert traza["decision"]["tipo"] == "biblioteca" and traza["fichas"][0]["cita"] == "Taller CAP, pág. 1"
    assert traza["tiempos"]["tokens_lectura"] == 50 and "total_ms" in traza["tiempos"]


def test_calculadora_entrega_resultado_exacto_aunque_el_modelo_explique(crear):
    llm = LLMFalso()
    r = crear(llm).responder("analiza 192.168.1.10/24")
    assert "📊 Resultado exacto" in r["texto"] and "Hosts útiles: 254" in r["texto"]
    assert "254" in llm.mensajes[1]["content"]                  # el modelo recibió el resultado exacto
    assert r["traza"]["herramienta"]["ok"] is True


def test_calculadora_valida_entradas(crear):
    r = crear().responder("analiza 300.1.1.1/24")
    assert "La calculadora no pudo" in r["texto"] and r["traza"]["herramienta"]["ok"] is False


def test_calculadora_pide_datos_que_faltan(crear):
    r = crear().responder("divide 10.0.0.0/24 por favor")
    assert "¿En cuántas subredes" in r["texto"]


def test_degradacion_si_el_modelo_falla(crear):
    r = crear(LLMFalso(falla=True)).responder("analiza 10.0.0.0/30")
    assert r["texto"].startswith("📊 Resultado exacto")           # sin explicación, pero con el resultado
    assert "llm caído" in r["traza"]["errores"][0]
    r2 = crear(LLMFalso(falla=True)).responder("¿Qué es CAP?")
    assert "Taller CAP, pág. 1" in r2["texto"]                   # entrega las fuentes encontradas


def test_fuera_de_tema_no_gasta_modelo(crear):
    llm = LLMFalso()
    r = crear(llm, tipo="fuera_de_tema").responder("receta de arepas")
    assert llm.mensajes is None and "Infraestructura de TI" in r["texto"]


def test_saludo_responde_directo(crear):
    r = crear().responder("hola")
    assert r["traza"]["decision"]["origen"] == "regla" and r["traza"]["decision"]["tipo"] == "directa"
