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
