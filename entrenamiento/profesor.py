# ⚠️ OBSOLETO (no se usó para el dataset final). Se conserva solo como registro de la alternativa
# descartada: el dataset final se escribió a mano con asistencia de Claude, se revisó por el estudiante
# y se arma con `python -m entrenamiento.construir_dataset`. Los encabezados de respuesta de este
# archivo son los viejos; los vigentes están en rag/prompts.py y entrenamiento/validar.py.
"""
Cliente del modelo "profesor" (OpenRouter): un modelo más grande que redacta los ejemplos
del dataset. Siempre pide JSON con esquema estricto y reintenta si algo falla.
"""

from __future__ import annotations

import json
import os
import time

import httpx


class ClienteProfesor:
    def __init__(self, modelo: str, api_key: str | None = None, timeout: float = 90, reintentos: int = 2):
        self.modelo = modelo
        self.api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self.http = httpx.Client(timeout=timeout)
        self.reintentos = reintentos
        self.costo_total = 0.0

    def json(self, sistema: str, usuario: str, esquema: dict, max_tokens: int = 900, temperatura: float = 0.8) -> dict:
        cuerpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "salida", "strict": True, "schema": esquema}},
            "provider": {"require_parameters": True},
            "temperature": temperatura,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        ultimo_error = None
        for intento in range(self.reintentos + 1):
            try:
                r = self.http.post("https://openrouter.ai/api/v1/chat/completions", json=cuerpo,
                                   headers={"Authorization": f"Bearer {self.api_key}", "X-Title": "agente-infra-dataset"})
                if r.status_code >= 400:
                    raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")
                datos = r.json()
                if "error" in datos:
                    raise RuntimeError(f"OpenRouter: {str(datos['error'])[:300]}")
                self.costo_total += (datos.get("usage") or {}).get("cost") or 0
                return json.loads(datos["choices"][0]["message"]["content"])
            except Exception as e:  # red, límite de tasa, JSON roto…
                ultimo_error = e
                time.sleep(2 * (intento + 1))
        raise RuntimeError(f"El profesor falló tras {self.reintentos + 1} intentos: {ultimo_error}")
