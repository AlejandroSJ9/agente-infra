"""
Prueba el agente completo por consola.

    docker compose run --rm agente python -m agente.cli "¿Qué es el teorema CAP?"
    docker compose run --rm agente python -m agente.cli "haz vlsm de 10.0.0.0/24 para 50, 20 y 10 hosts"
"""

import argparse

from agente.agente import crear_agente_desde_entorno


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pregunta")
    args = parser.parse_args()

    agente = crear_agente_desde_entorno()
    if agente.recepcionista is None:
        print("⚠️  Sin OPENROUTER_API_KEY: solo reglas; lo demás va a la biblioteca.\n")
    r = agente.responder(args.pregunta)
    d, t = r["traza"]["decision"], r["traza"]["tiempos"]

    print(f"❓ {args.pregunta}\n\n{r['texto']}\n")
    print("-" * 60)
    print(f"Decisión: {d['tipo']} (origen: {d['origen']}, confianza {d['confianza']:.2f}) – {d['razon']}")
    if r["traza"].get("herramienta"):
        print(f"Herramienta: {r['traza']['herramienta']}")
    for f in r["traza"].get("fichas", []):
        print(f"  ficha ({f['similitud']:.3f}) {f['cita'][:90]}")
    print("Tiempos (ms): " + ", ".join(f"{k}={v}" for k, v in t.items()))
    for e in r["traza"]["errores"]:
        print(f"⚠️  {e}")
    print(f"Traza: {r['traza']['id']}")


if __name__ == "__main__":
    main()
