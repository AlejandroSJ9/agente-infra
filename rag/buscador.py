"""
Buscador de la biblioteca: dada una pregunta, devuelve las k fichas más parecidas.

Uso (dentro del contenedor):
    python -m rag.buscador "¿Qué es el teorema CAP?"
    python -m rag.buscador "¿Qué es el teorema CAP?" -k 6

Cómo funciona:
    1. La pregunta se convierte en un vector con el mismo modelo del índice,
       con el prefijo "query: " que exige la familia e5.
    2. Como todos los vectores tienen longitud 1, el producto punto entre la
       pregunta y cada ficha es su similitud coseno (1 = mismo sentido, 0 = nada que ver).
    3. Se ordenan las fichas de mayor a menor similitud y se devuelven las k primeras.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from rag.indexar import Codificador, crear_codificador

K_MAXIMO = 20


class ErrorBusqueda(ValueError):
    """Entrada inválida para el buscador. El mensaje se puede mostrar tal cual."""


class Buscador:
    def __init__(self, carpeta: Path | str = "datos/indice", codificar: Codificador | None = None):
        carpeta = Path(carpeta)
        if not (carpeta / "meta.json").exists():
            raise SystemExit(f"No hay índice en {carpeta}. Ejecuta primero: python -m rag.indexar")

        self.meta = json.loads((carpeta / "meta.json").read_text(encoding="utf-8"))
        self.vectores = np.load(carpeta / "vectores.npy")
        with (carpeta / "fragmentos.jsonl").open(encoding="utf-8") as f:
            self.fragmentos = [json.loads(linea) for linea in f if linea.strip()]

        if len(self.fragmentos) != self.vectores.shape[0]:
            raise ValueError("El índice está corrupto: no coinciden fichas y vectores. Vuelve a indexar.")

        # Se usa SIEMPRE el modelo con que se construyó el índice: vectores de modelos
        # distintos no son comparables entre sí.
        self.codificar = codificar or crear_codificador(self.meta["modelo"])

    def buscar(self, pregunta: str, k: int = 4) -> list[dict]:
        if not isinstance(pregunta, str) or not pregunta.strip():
            raise ErrorBusqueda("La pregunta está vacía.")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= K_MAXIMO:
            raise ErrorBusqueda(f"k debe ser un entero entre 1 y {K_MAXIMO}.")
        k = min(k, len(self.fragmentos))

        vector_pregunta = self.codificar([f"query: {pregunta.strip()}"])[0]
        similitudes = self.vectores @ vector_pregunta          # una similitud por ficha
        mejores = np.argsort(-similitudes)[:k]                  # índices de mayor a menor

        resultados = []
        for posicion, i in enumerate(mejores, start=1):
            ficha = {c: v for c, v in self.fragmentos[i].items() if c != "texto_para_embedding"}
            ficha["posicion"] = posicion
            ficha["similitud"] = round(float(similitudes[i]), 4)
            resultados.append(ficha)
        return resultados


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca las fichas más relacionadas con una pregunta.")
    parser.add_argument("pregunta")
    parser.add_argument("-k", type=int, default=4, help="cuántas fichas devolver (por defecto 4)")
    parser.add_argument("--indice", default="datos/indice")
    args = parser.parse_args()

    t0 = time.perf_counter()
    buscador = Buscador(args.indice)
    t1 = time.perf_counter()
    resultados = buscador.buscar(args.pregunta, args.k)
    t2 = time.perf_counter()

    print(f"Pregunta: {args.pregunta}\n")
    for r in resultados:
        resumen = " ".join(r["texto"].split())[:220]
        print(f"#{r['posicion']}  similitud {r['similitud']:.3f}")
        print(f"    Fuente: {r['cita']}")
        print(f"    {resumen}...\n")
    print(f"Carga del modelo: {t1 - t0:.1f} s   |   Búsqueda: {(t2 - t1) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
