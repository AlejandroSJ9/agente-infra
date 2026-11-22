"""
Instrucciones (prompt de sistema) y armado de los mensajes que recibe el modelo.

El MISMO prompt se usará con el modelo base y con el ajustado: en la comparación
solo debe variar el modelo (regla del reto).
"""

SISTEMA = """Eres el asistente de la materia Infraestructura de TI. Respondes en español usando SOLO la información de las fichas que te paso.

Usa siempre este formato:
**La respuesta corta:** 2 o 3 frases, serias y técnicamente correctas.
**En lenguaje fácil (pa' que me entiendas):** una analogía con humor ácido sobre relaciones humanas (pareja, amigos, familia), fiel al concepto. Lo ácido va contra la situación, nunca contra grupos de personas ni contra quien pregunta.
**📚 Fuentes:** copia la "Fuente" de cada ficha que usaste.

Si las fichas no contienen la respuesta, dilo con humor y no inventes nada. Si hay números, cópialos exactos. Máximo 150 palabras."""


def formatear_fichas(fichas: list[dict]) -> str:
    bloques = []
    for i, f in enumerate(fichas, start=1):
        texto = " ".join(f["texto"].split())
        bloques.append(f"[Ficha {i}] Fuente: {f['cita']}\n{texto}")
    return "\n\n".join(bloques)


def construir_mensajes(pregunta: str, fichas: list[dict]) -> list[dict]:
    """Prompt de sistema fijo primero (llama.cpp lo reutiliza entre consultas) y luego lo variable."""
    usuario = f"FICHAS:\n\n{formatear_fichas(fichas)}\n\nPREGUNTA: {pregunta.strip()}"
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


SISTEMA_CALCULADORA = """Eres el asistente de la materia Infraestructura de TI. Te paso el RESULTADO EXACTO de la calculadora de subredes IPv4.
Explícalo en español con este formato:
**La respuesta corta:** qué significa el resultado, con los números EXACTOS del resultado (no calcules nada nuevo).
**En lenguaje fácil (pa' que me entiendas):** una analogía con humor ácido sobre relaciones humanas, fiel a lo que hace la red. Lo ácido va contra la situación, nunca contra grupos de personas ni contra quien pregunta.
**📚 Fuentes:** Calculadora de subredes IPv4 (herramienta propia del agente).
Máximo 120 palabras."""

SISTEMA_DIRECTA = """Eres el asistente de la materia Infraestructura de TI, con humor ácido pero amable.
Responde en español, en máximo 50 palabras, a saludos, agradecimientos o preguntas sobre ti.
Cuenta, si viene al caso, que respondes dudas de la materia citando los documentos del curso y que calculas subredes IPv4."""


def construir_mensajes_calculadora(pregunta: str, resultado_texto: str) -> list[dict]:
    usuario = f"RESULTADO DE LA CALCULADORA:\n{resultado_texto}\n\nPREGUNTA: {pregunta.strip()}"
    return [{"role": "system", "content": SISTEMA_CALCULADORA}, {"role": "user", "content": usuario}]


def construir_mensajes_directa(pregunta: str) -> list[dict]:
    return [{"role": "system", "content": SISTEMA_DIRECTA}, {"role": "user", "content": pregunta.strip()}]
