"""
El agente: une recepcionista, calculadora, buscador y modelo redactor, y deja una traza por pregunta.

Flujo:
    pregunta -> recepcionista -> decisión
        calculadora   -> calculadora (validada) -> resultado exacto + explicación del modelo
        biblioteca    -> buscador (k fichas)    -> respuesta del modelo con fuentes
        directa       -> modelo (respuesta breve)
        fuera_de_tema -> respuesta fija (sin gastar modelo)

Degradación controlada: si el modelo redactor falla, la calculadora igual entrega su
resultado exacto y la biblioteca entrega las fuentes encontradas.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agente import presentacion
from agente.recepcionista import ClienteRecepcionista, Decision, decidir
from herramientas.calculadora_subredes import ErrorEntrada, analizar_red, dividir_en_subredes, vlsm
from rag.prompts import construir_mensajes, construir_mensajes_calculadora, construir_mensajes_directa

ZONA = ZoneInfo("America/Bogota")


def ejecutar_calculadora(d: Decision) -> dict:
    """Traduce la decisión a una llamada de la calculadora. Lanza ErrorEntrada si faltan datos."""
    if not d.red:
        raise ErrorEntrada("Necesito la red, por ejemplo 192.168.1.0/24 o 192.168.1.0 255.255.255.0.")
    if d.funcion == "dividir_en_subredes":
        if d.cantidad is None:
            raise ErrorEntrada("¿En cuántas subredes la divido? Ejemplo: divide 10.0.0.0/24 en 4 subredes.")
        return dividir_en_subredes(d.red, d.cantidad, nube=d.nube)
    if d.funcion == "vlsm":
        if not d.hosts:
            raise ErrorEntrada("¿Cuántos hosts necesita cada segmento? Ejemplo: vlsm de 10.0.0.0/24 para 50, 20 y 10 hosts.")
        return vlsm(d.red, d.hosts, nube=d.nube)
    return analizar_red(d.red, nube=d.nube)


class Agente:
    def __init__(self, buscador, llm, recepcionista: ClienteRecepcionista | None,
                 carpeta_trazas: Path | str = "datos/trazas", k: int = 4):
        self.buscador = buscador
        self.llm = llm
        self.recepcionista = recepcionista
        self.carpeta_trazas = Path(carpeta_trazas)
        self.k = k
        self.modelo_redactor = os.environ.get("MODELO_GGUF", "?")

    # -- utilidades ------------------------------------------------------------------------
    def _redactar(self, mensajes: list[dict], traza: dict, max_tokens: int) -> str | None:
        t0 = time.perf_counter()
        try:
            texto, tiempos = self.llm.completar(mensajes, max_tokens=max_tokens)
        except Exception as e:
            traza["errores"].append(f"modelo redactor: {type(e).__name__}: {e}"[:300])
            return None
        traza["tiempos"].update({
            "redaccion_ms": round((time.perf_counter() - t0) * 1000),
            "lectura_ms": round(tiempos.get("prompt_ms", 0)), "tokens_lectura": tiempos.get("prompt_n"),
            "escritura_ms": round(tiempos.get("predicted_ms", 0)), "tokens_escritura": tiempos.get("predicted_n"),
        })
        return texto

    def _guardar_traza(self, traza: dict) -> None:
        self.carpeta_trazas.mkdir(parents=True, exist_ok=True)
        archivo = self.carpeta_trazas / f"{datetime.now(ZONA):%Y-%m-%d}.jsonl"
        with archivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(traza, ensure_ascii=False) + "\n")

    # -- flujo principal -------------------------------------------------------------------
    def responder(self, pregunta: str, canal: str = "cli", usuario: str | None = None) -> dict:
        inicio = time.perf_counter()
        traza = {
            "id": uuid.uuid4().hex[:12], "fecha": datetime.now(ZONA).isoformat(timespec="seconds"),
            "canal": canal, "usuario": usuario, "pregunta": pregunta,
            "modelo_redactor": self.modelo_redactor, "tiempos": {}, "errores": [],
        }

        decision = decidir(pregunta, self.recepcionista)
        traza["decision"] = decision.como_dict()
        traza["tiempos"]["decision_ms"] = round((time.perf_counter() - inicio) * 1000)

        if decision.tipo == "fuera_de_tema":
            texto = presentacion.elegir_fija(presentacion.FUERA_DE_TEMA, pregunta)

        elif decision.tipo == "directa":
            texto = self._redactar(construir_mensajes_directa(pregunta), traza, max_tokens=120) \
                or "¡Hola! Pregúntame de Infraestructura de TI o pídeme calcular una subred."

        elif decision.tipo == "calculadora":
            traza["herramienta"] = {"funcion": decision.funcion, "red": decision.red, "cantidad": decision.cantidad,
                                    "hosts": decision.hosts, "nube": decision.nube}
            try:
                resultado = ejecutar_calculadora(decision)
            except ErrorEntrada as e:
                traza["herramienta"].update(ok=False, error=str(e))
                texto = f"🧮 La calculadora no pudo con eso: {e}\n\nComo en las relaciones: con datos incompletos, mejor preguntar que suponer."
            else:
                traza["herramienta"]["ok"] = True
                exacto = presentacion.resultado_calculadora(decision.funcion or "analizar_red", resultado)
                explicacion = self._redactar(construir_mensajes_calculadora(pregunta, exacto), traza, max_tokens=250)
                texto = f"{explicacion}\n\n{exacto}" if explicacion else exacto

        else:  # biblioteca (también el respaldo cuando el recepcionista falla)
            t0 = time.perf_counter()
            fichas = self.buscador.buscar(pregunta, self.k)
            traza["tiempos"]["busqueda_ms"] = round((time.perf_counter() - t0) * 1000)
            traza["fichas"] = [{"id": f["id"], "cita": f["cita"], "similitud": f["similitud"]} for f in fichas]
            texto = self._redactar(construir_mensajes(pregunta, fichas), traza, max_tokens=350) \
                or presentacion.fichas_de_respaldo(fichas)

        traza["respuesta"] = texto
        traza["tiempos"]["total_ms"] = round((time.perf_counter() - inicio) * 1000)
        self._guardar_traza(traza)
        return {"texto": texto, "traza": traza}


def crear_agente_desde_entorno() -> Agente:
    """Construye el agente real (buscador + llama-server + OpenRouter) con las variables de .env."""
    from rag.buscador import Buscador
    from rag.responder import ClienteLLM

    recepcionista = ClienteRecepcionista() if os.environ.get("OPENROUTER_API_KEY") else None
    return Agente(Buscador(os.environ.get("INDICE", "datos/indice")),
                  ClienteLLM(os.environ.get("LLM_URL", "http://llm:8080")), recepcionista)
