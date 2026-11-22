"""
Evalúa el buscador con un conjunto fijo de preguntas (evaluacion/preguntas_busqueda.csv).

Uso (dentro del contenedor):
    python -m rag.evaluar_busqueda --indice datos/indice -k 4 --nombre titulo

Mide dos cosas distintas:

1. RECUPERACIÓN (preguntas con fuentes_validas):
   - hit@1, hit@3, hit@k: % de preguntas con al menos una fuente válida entre las primeras 1, 3 o k.
   - MRR@k: promedio de 1/posición de la primera fuente válida (1 = siempre primera; 0 = nunca).
   Una ficha cuenta como acierto si su (archivo, página) está en fuentes_validas.

2. SEPARABILIDAD (todas las preguntas):
   ¿La similitud del primer resultado distingue preguntas que SÍ están en el corpus de las que NO?
   - Si la menor similitud de las positivas supera a la mayor de las negativas, un umbral las separa.
   - Si se solapan, un umbral por sí solo no basta: se informa el mejor umbral posible y sus errores.

El conjunto de preguntas está congelado: no se edita para mejorar los números.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from rag.buscador import Buscador


def clave(ficha: dict) -> str:
    """'archivo#pagina', o solo 'archivo' si no tiene páginas (Markdown)."""
    return ficha["archivo"] if ficha.get("pagina") is None else f"{ficha['archivo']}#{ficha['pagina']}"


def cargar_preguntas(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8") as f:
        preguntas = list(csv.DictReader(f))
    for p in preguntas:
        p["validas"] = {s for s in p["fuentes_validas"].split("|") if s}
        p["positiva"] = bool(p["validas"])
    return preguntas


def evaluar(buscador: Buscador, preguntas: list[dict], k: int) -> list[dict]:
    filas = []
    for p in preguntas:
        resultados = buscador.buscar(p["pregunta"], k)
        claves = [clave(r) for r in resultados]
        rango = next((i for i, c in enumerate(claves, start=1) if c in p["validas"]), None)
        filas.append({
            "id": p["id"], "tipo": p["tipo"], "positiva": p["positiva"],
            "rango": rango,                                   # None = ninguna fuente válida en el top-k
            "similitud_top1": resultados[0]["similitud"],
            "top1": claves[0], "recuperadas": " | ".join(claves),
        })
    return filas


def metricas_recuperacion(filas: list[dict], k: int) -> dict:
    pos = [f for f in filas if f["positiva"]]
    if not pos:
        return {}
    def hit(n):
        return sum(1 for f in pos if f["rango"] is not None and f["rango"] <= n) / len(pos)
    return {
        "n": len(pos),
        "hit@1": hit(1), "hit@3": hit(min(3, k)), f"hit@{k}": hit(k),
        f"mrr@{k}": sum(1 / f["rango"] for f in pos if f["rango"]) / len(pos),
    }


def por_tipo(filas: list[dict], k: int) -> dict[str, tuple[int, int]]:
    """Para cada tipo de pregunta positiva: (aciertos en top-k, total)."""
    conteo = defaultdict(lambda: [0, 0])
    for f in filas:
        if f["positiva"]:
            conteo[f["tipo"]][1] += 1
            conteo[f["tipo"]][0] += f["rango"] is not None
    return {t: tuple(v) for t, v in sorted(conteo.items())}


def analisis_umbral(filas: list[dict]) -> dict:
    """
    Busca el umbral de similitud que mejor separa positivas (aceptar) de negativas (rechazar).
    Se usa exactitud balanceada para que el grupo más grande no domine.
    """
    pos = sorted(f["similitud_top1"] for f in filas if f["positiva"])
    neg = sorted(f["similitud_top1"] for f in filas if not f["positiva"])
    if not pos or not neg:
        return {}
    mejor = None
    for t in sorted(set(pos + neg)):
        acepta_pos = sum(s >= t for s in pos) / len(pos)
        rechaza_neg = sum(s < t for s in neg) / len(neg)
        balanceada = (acepta_pos + rechaza_neg) / 2
        if mejor is None or balanceada > mejor["exactitud_balanceada"]:
            mejor = {"umbral": t, "exactitud_balanceada": balanceada,
                     "positivas_rechazadas": sum(s < t for s in pos),
                     "negativas_aceptadas": sum(s >= t for s in neg)}
    return {
        "min_positivas": pos[0], "max_negativas": neg[-1],
        "margen": round(pos[0] - neg[-1], 4),        # > 0: separables con un umbral
        "separables": pos[0] > neg[-1],
        **mejor,
    }


def guardar(filas: list[dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el buscador con preguntas congeladas.")
    parser.add_argument("--preguntas", default="evaluacion/preguntas_busqueda.csv", type=Path)
    parser.add_argument("--indice", default="datos/indice")
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument("--nombre", default="base", help="nombre de la variante, para el archivo de salida")
    args = parser.parse_args()

    buscador = Buscador(args.indice)
    preguntas = cargar_preguntas(args.preguntas)
    filas = evaluar(buscador, preguntas, args.k)
    salida = Path("datos/evaluacion") / f"busqueda_{args.nombre}.csv"
    guardar(filas, salida)

    m = metricas_recuperacion(filas, args.k)
    print(f"Variante: {args.nombre}  |  índice: {buscador.meta.get('modelo')}, "
          f"contexto={buscador.meta.get('contexto', 'titulo')}  |  k={args.k}\n")
    print(f"RECUPERACIÓN ({m['n']} preguntas con fuente)")
    for nombre, valor in m.items():
        if nombre != "n":
            print(f"  {nombre:<7} {valor:6.1%}" if nombre.startswith("hit") else f"  {nombre:<7} {valor:6.3f}")

    print("\nPOR TIPO (aciertos en top-k / total)")
    for tipo, (a, n) in por_tipo(filas, args.k).items():
        print(f"  {tipo:<16} {a}/{n}")

    print("\nFALLOS (ninguna fuente válida en el top-k)")
    fallos = [f for f in filas if f["positiva"] and f["rango"] is None]
    for f in fallos or [{"id": "—", "top1": "ninguno"}]:
        print(f"  {f['id']}: el primero fue {f['top1']}")

    u = analisis_umbral(filas)
    print("\nSEPARABILIDAD (similitud del primer resultado)")
    print(f"  Positivas: mínimo {u['min_positivas']:.3f}   |   Negativas: máximo {u['max_negativas']:.3f}")
    print(f"  Margen: {u['margen']:+.3f}  ->  {'SEPARABLES con un umbral' if u['separables'] else 'SE SOLAPAN'}")
    print(f"  Mejor umbral: {u['umbral']:.3f}  (exactitud balanceada {u['exactitud_balanceada']:.1%}; "
          f"rechaza {u['positivas_rechazadas']} positivas, acepta {u['negativas_aceptadas']} negativas)")
    print(f"\nDetalle por pregunta: {salida}")


if __name__ == "__main__":
    main()
