"""
Textos que NO escribe el modelo: el resultado exacto de la calculadora y las respuestas fijas.
Así los números siempre salen tal cual los calculó la herramienta, aunque el modelo se equivoque.
"""

from __future__ import annotations

import hashlib

MAX_SUBREDES_MOSTRADAS = 16

FUERA_DE_TEMA = [
    "Eso no es de Infraestructura de TI. Yo solo sé de servidores, redes y nubes… y la única nube que manejo no da lluvia. 🌧️ Pregúntame algo de la materia.",
    "Uy, eso está más fuera de mi alcance que tu ex de tu vida. 🙃 Yo respondo sobre Infraestructura de TI y calculo subredes IPv4.",
    "Me encantaría opinar, pero mi relación es exclusiva con la Infraestructura de TI. Pregúntame de CAP, AWS, contenedores o subredes.",
]


def elegir_fija(opciones: list[str], semilla: str) -> str:
    """Elige siempre la misma respuesta para la misma pregunta (reproducible en las pruebas)."""
    return opciones[int(hashlib.md5(semilla.encode()).hexdigest(), 16) % len(opciones)]


def _rango(r: dict) -> str:
    return f"{r['primer_host']} – {r['ultimo_host']}"


def resultado_calculadora(funcion: str, r: dict) -> str:
    lineas = ["📊 Resultado exacto (calculadora)"]
    if funcion == "analizar_red":
        lineas += [
            f"Red: {r['red']}  |  Máscara: {r['mascara']} (/{r['prefijo']})",
            f"Hosts útiles: {r['hosts_utiles']}  |  Rango: {_rango(r)}",
            f"Broadcast: {r['broadcast'] or 'no aplica'}  |  Tipo: {r['tipo']}",
        ]
        if r.get("nota"):
            lineas.append(f"Nota: {r['nota']}")
    elif funcion == "dividir_en_subredes":
        lineas.append(f"{r['red_original']} → {r['subredes_obtenidas']} subredes /{r['nuevo_prefijo']} "
                      f"(máscara {r['nueva_mascara']}), {r['hosts_utiles_por_subred']} hosts útiles cada una")
        lineas.append(f"Bits prestados: {r['bits_prestados']}")
        for i, s in enumerate(r["subredes"][:MAX_SUBREDES_MOSTRADAS], start=1):
            lineas.append(f"{i}. {s['red']}  ({_rango(s)})")
        if len(r["subredes"]) > MAX_SUBREDES_MOSTRADAS:
            lineas.append(f"… y {len(r['subredes']) - MAX_SUBREDES_MOSTRADAS} subredes más")
    elif funcion == "vlsm":
        lineas.append(f"Red: {r['red_original']}")
        for a in r["asignaciones"]:
            lineas.append(f"• {a['hosts_pedidos']} hosts → {a['red']} ({a['hosts_utiles']} útiles, {_rango(a)})")
        lineas.append(f"Usadas: {r['direcciones_usadas']} direcciones  |  Libres: {r['direcciones_libres']}")
    for aviso in r.get("avisos", []):
        lineas.append(f"⚠️ {aviso}")
    return "\n".join(lineas)


def fichas_de_respaldo(fichas: list[dict]) -> str:
    """Si el modelo no responde, al menos se entregan las fuentes encontradas."""
    lineas = ["😵 El modelo se quedó dormido y no pudo redactar. Pero estas fichas hablan de tu pregunta:"]
    lineas += [f"• {f['cita']}" for f in fichas]
    return "\n".join(lineas)
