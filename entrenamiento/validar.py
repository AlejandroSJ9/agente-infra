"""
Validación automática de cada ejemplo del dataset (antes de la revisión humana).

Un ejemplo se descarta si:
    - no respeta el formato (las 3 secciones, en orden, con sus nombres exactos)
    - es demasiado largo (en CPU, cada palabra extra cuesta tiempo)
    - cita una fuente que NO estaba en sus fichas (cita inventada)
    - en la calculadora, menciona un número que no está en el resultado exacto (número inventado)
    - pone entre «comillas angulares» un texto que no aparece EXACTO en sus fichas (cita textual inventada)
    - contiene bloques <think>
"""

from __future__ import annotations

import re

SECCIONES = ("**La respuesta técnica:**", "**En lenguaje fácil (pa' que me entiendas):**", "**📚 Fuentes:**")
MAX_PALABRAS = {"biblioteca": 230, "abstencion": 200, "calculadora": 170, "directa": 60}
_CITA_TEXTUAL = re.compile(r"«([^»]+)»")

_IP_O_NUMERO = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?|\d+(?:[.,]\d+)*")


def contar_palabras(texto: str) -> int:
    return len(texto.split())


def problemas_formato(respuesta: str, tipo: str) -> list[str]:
    problemas = []
    if "<think>" in respuesta:
        problemas.append("contiene <think>")
    if contar_palabras(respuesta) > MAX_PALABRAS[tipo]:
        problemas.append(f"muy larga ({contar_palabras(respuesta)} palabras)")
    if tipo == "directa":
        return problemas
    posiciones = [respuesta.find(s) for s in SECCIONES]
    if -1 in posiciones:
        faltan = [s for s, p in zip(SECCIONES, posiciones) if p == -1]
        problemas.append(f"faltan secciones: {faltan}")
    elif posiciones != sorted(posiciones):
        problemas.append("secciones fuera de orden")
    return problemas


def seccion_fuentes(respuesta: str) -> str:
    i = respuesta.find(SECCIONES[2])
    return respuesta[i + len(SECCIONES[2]):] if i >= 0 else ""


def problemas_fuentes(respuesta: str, titulos_en_contexto: set[str], todos_los_titulos: set[str],
                      tiene_respuesta: bool) -> list[str]:
    """Las fuentes citadas deben ser documentos que estaban en las fichas entregadas."""
    fuentes = seccion_fuentes(respuesta)
    citados = {t for t in todos_los_titulos if t in fuentes}
    problemas = []
    inventados = citados - titulos_en_contexto
    if inventados:
        problemas.append(f"cita documentos que no estaban en sus fichas: {sorted(inventados)}")
    if tiene_respuesta and not (citados & titulos_en_contexto):
        problemas.append("responde pero no cita ninguna ficha")
    return problemas


def numeros(texto: str) -> set[str]:
    return {n.replace(",", "") for n in _IP_O_NUMERO.findall(texto)}


def problemas_numeros(explicacion: str, resultado: str, pregunta: str) -> list[str]:
    """Todo número de la explicación debe venir del resultado exacto o de la pregunta (o ser 0–10)."""
    permitidos = numeros(resultado) | numeros(pregunta) | {str(i) for i in range(11)}
    # también se permiten las partes de las IPs y prefijos del resultado ("26" de "/26", "192" de una IP)
    for n in list(permitidos):
        permitidos |= set(re.split(r"[./]", n))
        permitidos.add(n.split("/")[0])                  # la IP sin prefijo: "10.0.0.5/24" -> "10.0.0.5"
    texto = explicacion.split(SECCIONES[2])[0]           # la sección de fuentes no cuenta
    inventados = sorted(numeros(texto) - permitidos)
    return [f"números que no están en el resultado: {inventados}"] if inventados else []


def normalizar(texto: str) -> str:
    """Compara sin importar saltos de línea, espacios dobles ni el tipo de comillas internas."""
    texto = texto.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(texto.split())


def citas_textuales(respuesta: str) -> list[str]:
    return [c.strip() for c in _CITA_TEXTUAL.findall(respuesta)]


def problemas_citas(respuesta: str, texto_fuente: str, minimo: int) -> list[str]:
    """Cada «cita» debe existir tal cual en las fichas (o en el resultado de la calculadora)."""
    citas = citas_textuales(respuesta)
    fuente = normalizar(texto_fuente)
    problemas = [f"cita textual que no está en las fichas: «{c[:60]}»" for c in citas if normalizar(c) not in fuente]
    if len(citas) < minimo:
        problemas.append(f"faltan citas textuales (tiene {len(citas)}, mínimo {minimo})")
    if len(citas) > 3:
        problemas.append(f"demasiadas citas textuales ({len(citas)})")
    return problemas
