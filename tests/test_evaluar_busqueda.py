"""Pruebas de las métricas del evaluador (funciones puras, sin modelos)."""

from rag.evaluar_busqueda import analisis_umbral, clave, metricas_recuperacion, por_tipo
from rag.indexar import texto_a_vectorizar


def fila(id, positiva, rango, sim, tipo="parafrasis"):
    return {"id": id, "tipo": tipo, "positiva": positiva, "rango": rango, "similitud_top1": sim}


def test_clave_con_y_sin_pagina():
    assert clave({"archivo": "a.pdf", "pagina": 3}) == "a.pdf#3"
    assert clave({"archivo": "b.md", "pagina": None}) == "b.md"


def test_metricas_de_recuperacion():
    filas = [fila("1", True, 1, .9), fila("2", True, 3, .9), fila("3", True, None, .9), fila("4", False, None, .8)]
    m = metricas_recuperacion(filas, k=4)
    assert m["n"] == 3                                   # las negativas no cuentan
    assert m["hit@1"] == 1 / 3 and m["hit@3"] == 2 / 3 and m["hit@4"] == 2 / 3
    assert abs(m["mrr@4"] - (1 + 1 / 3) / 3) < 1e-9


def test_por_tipo():
    filas = [fila("1", True, 1, .9, "catalogo"), fila("2", True, None, .9, "catalogo")]
    assert por_tipo(filas, 4) == {"catalogo": (1, 2)}


def test_umbral_separable():
    filas = [fila("p1", True, 1, .90), fila("p2", True, 1, .88), fila("n1", False, None, .80)]
    u = analisis_umbral(filas)
    assert u["separables"] and u["margen"] > 0
    assert u["exactitud_balanceada"] == 1.0 and u["umbral"] == .88


def test_umbral_solapado():
    filas = [fila("p1", True, 1, .90), fila("p2", True, 1, .82), fila("n1", False, None, .85)]
    u = analisis_umbral(filas)
    assert not u["separables"] and u["exactitud_balanceada"] < 1.0


def test_texto_a_vectorizar():
    f = {"texto": "hola", "texto_para_embedding": "passage: Título. Sección\nhola"}
    assert texto_a_vectorizar(f, "titulo") == f["texto_para_embedding"]
    assert texto_a_vectorizar(f, "ninguno") == "passage: hola"
