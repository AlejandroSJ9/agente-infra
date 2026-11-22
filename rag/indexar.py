"""
Construye el índice del buscador: convierte cada ficha en un vector (embedding)
y guarda los vectores junto con las fichas.

Uso (dentro del contenedor):
    python -m rag.ingesta      # 1) corpus/        -> datos/fragmentos.jsonl
    python -m rag.indexar      # 2) fragmentos     -> datos/indice/

Qué guarda en datos/indice/:
    vectores.npy        una fila por ficha (float32, normalizada a longitud 1)
    fragmentos.jsonl    las fichas, en el mismo orden que las filas
    meta.json           modelo usado, dimensión, cantidad, fecha y huella del corpus

Por qué no hay base de datos vectorial: con ~150 fichas, comparar la pregunta
contra todas (búsqueda exacta) toma menos de un milisegundo. Un índice aproximado
(HNSW, Qdrant, etc.) solo se justifica con cientos de miles de vectores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

MODELO_POR_DEFECTO = "intfloat/multilingual-e5-small"

# Una función que recibe textos y devuelve una matriz (n_textos x dimensión) normalizada.
Codificador = Callable[[list[str]], np.ndarray]


def crear_codificador(nombre_modelo: str = MODELO_POR_DEFECTO) -> Codificador:
    """Carga el modelo de embeddings (se descarga la primera vez y queda en caché)."""
    from sentence_transformers import SentenceTransformer  # import aquí: es pesado

    modelo = SentenceTransformer(nombre_modelo, device="cpu")

    def codificar(textos: list[str]) -> np.ndarray:
        vectores = modelo.encode(textos, batch_size=32, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)
        return vectores.astype(np.float32)

    return codificar


def cargar_fragmentos(ruta: Path) -> list[dict]:
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}. Ejecuta primero: python -m rag.ingesta")
    with ruta.open(encoding="utf-8") as f:
        fragmentos = [json.loads(linea) for linea in f if linea.strip()]
    if not fragmentos:
        raise SystemExit(f"{ruta} está vacío: no hay fichas que indexar.")
    return fragmentos


def construir_indice(fragmentos: list[dict], codificar: Codificador,
                     nombre_modelo: str, carpeta: Path) -> dict:
    """Calcula los vectores y escribe los tres archivos del índice. Devuelve meta."""
    textos = [f["texto_para_embedding"] for f in fragmentos]  # ya traen el prefijo "passage: "
    vectores = codificar(textos)

    if vectores.shape[0] != len(fragmentos):
        raise ValueError("El modelo devolvió una cantidad de vectores distinta a la de fichas.")
    normas = np.linalg.norm(vectores, axis=1)
    if not np.allclose(normas, 1.0, atol=1e-3):
        raise ValueError("Los vectores deben venir normalizados (longitud 1).")

    carpeta.mkdir(parents=True, exist_ok=True)
    np.save(carpeta / "vectores.npy", vectores)
    with (carpeta / "fragmentos.jsonl").open("w", encoding="utf-8") as f:
        for frag in fragmentos:
            f.write(json.dumps(frag, ensure_ascii=False) + "\n")

    huella = hashlib.sha256("".join(fr["hash"] for fr in fragmentos).encode()).hexdigest()[:16]
    meta = {
        "modelo": nombre_modelo,
        "dimension": int(vectores.shape[1]),
        "fichas": len(fragmentos),
        "huella_corpus": huella,
        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (carpeta / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Convierte las fichas en vectores para el buscador.")
    parser.add_argument("--fragmentos", default="datos/fragmentos.jsonl", type=Path)
    parser.add_argument("--salida", default="datos/indice", type=Path)
    parser.add_argument("--modelo", default=MODELO_POR_DEFECTO)
    args = parser.parse_args()

    fragmentos = cargar_fragmentos(args.fragmentos)
    t0 = time.perf_counter()
    codificar = crear_codificador(args.modelo)
    t1 = time.perf_counter()
    meta = construir_indice(fragmentos, codificar, args.modelo, args.salida)
    t2 = time.perf_counter()

    print(f"Modelo:     {meta['modelo']} (dimensión {meta['dimension']})")
    print(f"Fichas:     {meta['fichas']}")
    print(f"Carga:      {t1 - t0:.1f} s   |   Vectorización: {t2 - t1:.1f} s")
    print(f"Índice en:  {args.salida}/")


if __name__ == "__main__":
    main()
