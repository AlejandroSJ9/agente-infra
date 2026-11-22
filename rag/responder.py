"""
Respuesta completa por consola: pregunta -> buscador -> fichas -> modelo -> respuesta.

Uso (con el contenedor llm encendido):
    docker compose up -d llm
    docker compose run --rm agente python -m rag.responder "¿Qué es el teorema CAP?"

Además de la respuesta, imprime cuánto tardó cada etapa. llama.cpp informa por separado:
    - lectura (prefill): procesar las instrucciones + fichas + pregunta
    - escritura (decode): generar la respuesta token por token
"""

from __future__ import annotations

import argparse
import os
import re
import time

import httpx

from rag.buscador import Buscador
from rag.prompts import construir_mensajes

_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.DOTALL)


def limpiar_respuesta(texto: str) -> str:
    """Quita bloques <think>...</think> si el modelo igual los genera."""
    return _PENSAMIENTO.sub("", texto).strip()


class ClienteLLM:
    """Cliente mínimo para la API compatible con OpenAI de llama-server."""

    def __init__(self, url: str, timeout: float = 300):
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=timeout)

    def completar(self, mensajes: list[dict], max_tokens: int = 350) -> tuple[str, dict]:
        cuerpo = {
            "messages": mensajes,
            "max_tokens": max_tokens,
            # Valores recomendados por Qwen para el modo sin razonamiento
            "temperature": 0.7, "top_p": 0.8, "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = self.http.post(f"{self.url}/v1/chat/completions", json=cuerpo)
        r.raise_for_status()
        datos = r.json()
        texto = datos["choices"][0]["message"].get("content") or ""
        return limpiar_respuesta(texto), datos.get("timings", {})


def main() -> None:
    parser = argparse.ArgumentParser(description="Pregunta -> buscador -> modelo -> respuesta.")
    parser.add_argument("pregunta")
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument("--indice", default="datos/indice")
    parser.add_argument("--llm-url", default=os.environ.get("LLM_URL", "http://llm:8080"))
    args = parser.parse_args()

    buscador = Buscador(args.indice)
    llm = ClienteLLM(args.llm_url)

    t0 = time.perf_counter()
    fichas = buscador.buscar(args.pregunta, args.k)
    t1 = time.perf_counter()
    respuesta, tiempos = llm.completar(construir_mensajes(args.pregunta, fichas))
    t2 = time.perf_counter()

    print(f"❓ {args.pregunta}\n")
    print(respuesta)
    print("\n" + "-" * 60)
    print("Fichas usadas:")
    for f in fichas:
        print(f"  #{f['posicion']} ({f['similitud']:.3f}) {f['cita'][:90]}")
    print("-" * 60)
    print(f"Búsqueda:   {(t1 - t0) * 1000:7.0f} ms")
    if tiempos:
        print(f"Lectura:    {tiempos['prompt_ms']:7.0f} ms  ({tiempos['prompt_n']} tokens, "
              f"{tiempos['prompt_per_second']:.1f} tok/s)")
        print(f"Escritura:  {tiempos['predicted_ms']:7.0f} ms  ({tiempos['predicted_n']} tokens, "
              f"{tiempos['predicted_per_second']:.1f} tok/s)")
    print(f"TOTAL:      {(t2 - t0) * 1000:7.0f} ms")


if __name__ == "__main__":
    main()
