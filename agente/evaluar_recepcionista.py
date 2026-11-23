"""
Prueba comparativa del recepcionista: mide un modelo de OpenRouter con preguntas etiquetadas.

    docker compose run --rm agente python -m agente.evaluar_recepcionista --modelo google/gemini-3.1-flash-lite
    docker compose run --rm agente python -m agente.evaluar_recepcionista --modelo openai/gpt-oss-20b
    docker compose run --rm agente python -m agente.evaluar_recepcionista --modelo google/gemini-2.5-flash-lite

Por defecto evalúa SOLO el modelo (sin reglas), para comparar modelos en igualdad de condiciones.
Con --con-reglas evalúa el recepcionista completo, como funciona en producción.

Mide:
    - exactitud del tipo (biblioteca / calculadora / directa / fuera_de_tema)
    - exactitud de argumentos en las preguntas de calculadora (función, red, cantidad, hosts, nube)
    - fallos técnicos (error de API o JSON inválido)
    - latencia p50 / p95 y costo total
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import statistics
from pathlib import Path

from agente.recepcionista import ClienteRecepcionista, decidir, decidir_por_reglas


def normalizar_red(red: str | None) -> str:
    return " ".join((red or "").split()).replace(" /", "/").replace("/ ", "/")


def esperado(fila: dict) -> dict:
    return {
        "tipo": fila["tipo"], "funcion": fila["funcion"] or None, "red": normalizar_red(fila["red"]) or None,
        "cantidad": int(fila["cantidad"]) if fila["cantidad"] else None,
        "hosts": [int(h) for h in fila["hosts"].split("|")] if fila["hosts"] else None,
        "nube": fila["nube"] or None,
    }


def red_canonica(red: str | None) -> str | None:
    """'10.20.30.0 255.255.255.192' y '10.20.30.0/26' son la misma red -> '10.20.30.0/26'."""
    texto = normalizar_red(red)
    if not texto:
        return None
    try:
        return ipaddress.IPv4Interface(texto.replace(" ", "/")).with_prefixlen
    except ValueError:
        return texto


# Campos que cada función de la calculadora realmente usa
CAMPOS_USADOS = {
    "analizar_red": ("red", "nube"),
    "dividir_en_subredes": ("red", "cantidad", "nube"),
    "vlsm": ("red", "hosts", "nube"),
}


def argumentos_correctos(d, e: dict) -> bool:
    """Estricto: todos los campos idénticos como texto, incluso los que la función no usa."""
    return (d.funcion == e["funcion"] and normalizar_red(d.red) == e["red"] and d.cantidad == e["cantidad"]
            and (d.hosts or None) == e["hosts"] and d.nube == e["nube"])


def argumentos_equivalentes(d, e: dict) -> bool:
    """Semántico: misma función y mismos valores en los campos que esa función usa (redes por significado)."""
    if d.funcion != e["funcion"]:
        return False
    obtenido = {"red": red_canonica(d.red), "cantidad": d.cantidad, "hosts": d.hosts or None, "nube": d.nube}
    esperado_ = {"red": red_canonica(e["red"]), "cantidad": e["cantidad"], "hosts": e["hosts"], "nube": e["nube"]}
    return all(obtenido[c] == esperado_[c] for c in CAMPOS_USADOS.get(e["funcion"], ()))


def percentil(valores: list[float], p: float) -> float:
    valores = sorted(valores)
    return valores[min(len(valores) - 1, round(p * (len(valores) - 1)))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", required=True)
    parser.add_argument("--preguntas", default="evaluacion/preguntas_recepcionista.csv", type=Path)
    parser.add_argument("--con-reglas", action="store_true")
    args = parser.parse_args()

    cliente = ClienteRecepcionista(modelos=[args.modelo])      # un solo modelo: sin respaldo
    filas = list(csv.DictReader(args.preguntas.open(encoding="utf-8")))
    resultados = []
    for f in filas:
        e = esperado(f)
        d = decidir(f["pregunta"], cliente, solo_modelo=not args.con_reglas)
        fallo_tecnico = d.origen == "respaldo"
        resultados.append({
            "id": f["id"], "esperado": e["tipo"], "obtenido": d.tipo, "origen": d.origen,
            "tipo_ok": d.tipo == e["tipo"] and not fallo_tecnico,
            "args_ok": argumentos_correctos(d, e) if e["tipo"] == "calculadora" else None,
            "args_equivalentes": argumentos_equivalentes(d, e) if e["tipo"] == "calculadora" else None,
            "fallo_tecnico": fallo_tecnico, "latencia_ms": round(d.latencia_ms), "costo_usd": d.costo_usd or 0,
            "detalle": d.extra.get("error", "") or f"{d.funcion} {d.red} {d.cantidad} {d.hosts} {d.nube}",
            "razon": d.razon,
        })
        print(f"{f['id']}: esperado {e['tipo']:<13} obtenido {d.tipo:<13} {'✅' if resultados[-1]['tipo_ok'] else '❌'}")

    n = len(resultados)
    calc = [r for r in resultados if r["esperado"] == "calculadora"]
    latencias = [r["latencia_ms"] for r in resultados if r["origen"].startswith("modelo")]
    print(f"\n=== {args.modelo} {'(con reglas)' if args.con_reglas else '(solo modelo)'} ===")
    print(f"Tipo correcto:        {sum(r['tipo_ok'] for r in resultados)}/{n}")
    print(f"Argumentos (estricto):  {sum(bool(r['args_ok']) for r in calc)}/{len(calc)}  "
          f"|  (semántico): {sum(bool(r['args_equivalentes']) for r in calc)}/{len(calc)}  (preguntas de calculadora)")
    print(f"Fallos técnicos:      {sum(r['fallo_tecnico'] for r in resultados)}/{n}")
    if latencias:
        print(f"Latencia:             p50 {percentil(latencias, .5):.0f} ms  |  p95 {percentil(latencias, .95):.0f} ms"
              f"  (media {statistics.mean(latencias):.0f} ms)")
    print(f"Costo total:          ${sum(r['costo_usd'] for r in resultados):.5f} por {n} preguntas")

    print("\nERRORES:")
    for r in resultados:
        if not r["tipo_ok"] or r["args_ok"] is False:
            print(f"  {r['id']}: esperado {r['esperado']}, obtenido {r['obtenido']} | {r['detalle']} | {r['razon']}")

    nombre = args.modelo.replace("/", "_") + ("_reglas" if args.con_reglas else "")
    salida = Path("datos/evaluacion") / f"recepcionista_{nombre}.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(resultados[0]))
        w.writeheader()
        w.writerows(resultados)
    print(f"\nDetalle: {salida}")


if __name__ == "__main__":
    main()
