"""Pruebas del armado del prompt y la limpieza de respuestas (sin modelo)."""

from rag.prompts import SISTEMA, construir_mensajes, formatear_fichas
from rag.responder import limpiar_respuesta

FICHAS = [
    {"cita": "Teorema CAP (infografía 2/3) (Garavito, 2026)", "texto": "C – Consistencia:\n  cada lectura..."},
    {"cita": "Taller CAP, pág. 1", "texto": "Idea central: CAP analiza..."},
]


def test_fichas_numeradas_con_su_fuente():
    texto = formatear_fichas(FICHAS)
    assert texto.startswith("[Ficha 1] Fuente: Teorema CAP (infografía 2/3)")
    assert "[Ficha 2] Fuente: Taller CAP, pág. 1" in texto
    assert "C – Consistencia: cada lectura..." in texto        # espacios y saltos normalizados


def test_mensajes_sistema_primero_y_pregunta_al_final():
    mensajes = construir_mensajes("  ¿Qué es CAP?  ", FICHAS)
    assert mensajes[0] == {"role": "system", "content": SISTEMA}
    assert mensajes[1]["role"] == "user"
    assert mensajes[1]["content"].endswith("PREGUNTA: ¿Qué es CAP?")


def test_formato_pedido_en_el_prompt():
    for seccion in ("La respuesta técnica", "En lenguaje fácil (pa' que me entiendas)", "Fuentes"):
        assert seccion in SISTEMA


def test_limpia_bloques_de_pensamiento():
    assert limpiar_respuesta("<think>mmm...\nno sé</think>\n\nRespuesta final") == "Respuesta final"
    assert limpiar_respuesta("Sin pensamiento") == "Sin pensamiento"
