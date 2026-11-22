"""
Pruebas del indexador y el buscador con un codificador falso (sin descargar modelos).
El codificador falso cuenta palabras: dos textos con palabras en común quedan cerca.
Ejecutar con:  python -m pytest -v
"""

import hashlib
import json

import numpy as np
import pytest

from rag.buscador import Buscador, ErrorBusqueda
from rag.indexar import construir_indice

DIM = 64


def codificador_falso(textos):
    matriz = np.zeros((len(textos), DIM), dtype=np.float32)
    for fila, texto in enumerate(textos):
        texto = texto.removeprefix("query: ").removeprefix("passage: ").lower()
        for palabra in texto.split():
            columna = int(hashlib.md5(palabra.encode()).hexdigest(), 16) % DIM
            matriz[fila, columna] += 1
    matriz /= np.linalg.norm(matriz, axis=1, keepdims=True)
    return matriz


def ficha(i, texto):
    return {"id": f"doc:{i}:0", "hash": f"h{i}", "cita": f"Documento {i}", "texto": texto,
            "texto_para_embedding": f"passage: {texto}"}


FICHAS = [
    ficha(1, "teorema cap consistencia disponibilidad particiones"),
    ficha(2, "contenedores docker imagenes volumenes redes"),
    ficha(3, "terraform infraestructura como codigo estado plan"),
]


@pytest.fixture
def indice(tmp_path):
    meta = construir_indice(FICHAS, codificador_falso, "modelo-falso", tmp_path)
    return tmp_path, meta


def test_construye_los_tres_archivos(indice):
    carpeta, meta = indice
    assert {"vectores.npy", "fragmentos.jsonl", "meta.json"} <= {p.name for p in carpeta.iterdir()}
    assert meta["fichas"] == 3 and meta["dimension"] == DIM


def test_encuentra_la_ficha_correcta(indice):
    buscador = Buscador(indice[0], codificar=codificador_falso)
    resultados = buscador.buscar("¿qué dice el teorema cap sobre consistencia?", k=2)
    assert resultados[0]["cita"] == "Documento 1"
    assert resultados[0]["posicion"] == 1
    assert resultados[0]["similitud"] >= resultados[1]["similitud"]
    assert "texto_para_embedding" not in resultados[0]


def test_k_mayor_que_las_fichas_devuelve_todas(indice):
    assert len(Buscador(indice[0], codificar=codificador_falso).buscar("docker", k=10)) == 3


@pytest.mark.parametrize("pregunta, k", [("", 4), ("   ", 4), ("docker", 0), ("docker", 21),
                                         ("docker", 2.5), ("docker", True)])
def test_entradas_invalidas(indice, pregunta, k):
    with pytest.raises(ErrorBusqueda):
        Buscador(indice[0], codificar=codificador_falso).buscar(pregunta, k)


def test_detecta_indice_corrupto(indice):
    carpeta, _ = indice
    with (carpeta / "fragmentos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(FICHAS[0]) + "\n")      # una ficha de más
    with pytest.raises(ValueError):
        Buscador(carpeta, codificar=codificador_falso)


def test_rechaza_vectores_sin_normalizar(tmp_path):
    def sin_normalizar(textos):
        return np.ones((len(textos), DIM), dtype=np.float32)
    with pytest.raises(ValueError):
        construir_indice(FICHAS, sin_normalizar, "x", tmp_path)
