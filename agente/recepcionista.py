"""
Recepcionista: decide qué hacer con cada pregunta. Es la lógica de decisión del agente.

Etapa 1, REGLAS (deterministas, gratis, instantáneas):
    - Hay una IPv4 con prefijo o máscara      -> calculadora (y se extraen los argumentos)
    - Es solo un saludo o agradecimiento      -> respuesta directa
Etapa 2, MODELO POR API (solo si ninguna regla aplica):
    - Un LLM de OpenRouter clasifica y devuelve JSON con un esquema estricto.
    - Si la API falla o la confianza es baja  -> biblioteca (respaldo seguro: buscar y,
      si no hay evidencia, el modelo redactor dice que no sabe).

Tipos de decisión:
    biblioteca | calculadora | directa | fuera_de_tema
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

import httpx

TIPOS = ("biblioteca", "calculadora", "directa", "fuera_de_tema")
FUNCIONES = ("analizar_red", "dividir_en_subredes", "vlsm")
CONFIANZA_MINIMA = 0.5

MODELO_PRINCIPAL = "google/gemini-3.1-flash-lite"
MODELO_RESPALDO = "openai/gpt-oss-20b"        # otra empresa: fallas independientes


@dataclass
class Decision:
    tipo: str
    origen: str                      # "regla", "modelo:<id>" o "respaldo"
    funcion: str | None = None
    red: str | None = None
    cantidad: int | None = None
    hosts: list[int] | None = None
    nube: str | None = None
    confianza: float = 1.0
    razon: str = ""
    latencia_ms: float = 0.0
    costo_usd: float | None = None
    extra: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Etapa 1: reglas
# ---------------------------------------------------------------------------

_IP = r"\d{1,3}(?:\.\d{1,3}){3}"
# "10.0.0.0/24", "10.0.0.0 /24", "10.0.0.0/255.255.255.0", "10.0.0.0 255.255.255.0", "10.0.0.0 máscara 255.255.255.0"
_MASCARA = r"(?:255|254|252|248|240|224|192|128)(?:\.\d{1,3}){3}"
_RED = re.compile(rf"({_IP})\s*(?:/\s*({_MASCARA}|\d{{1,2}})\b|\s+(?:con\s+)?(?:(?:la\s+)?m[aá]scara\s+)?({_MASCARA}))",
                  re.IGNORECASE)
_SALUDO = re.compile(r"^\s*(hola+|buenas(?: tardes| noches)?|buen(?:os)? d[ií]as?|hey|holi|qu[eé] (?:m[aá]s|hubo)|"
                     r"gracias|muchas gracias|ok(?:ay)?|listo|chao|adi[oó]s)\s*[!¡.?¿]*\s*$", re.IGNORECASE)


def extraer_red(texto: str) -> str | None:
    """Devuelve 'ip/prefijo' o 'ip mascara' tal como lo entiende la calculadora."""
    m = _RED.search(texto)
    if not m:
        return None
    ip, prefijo, mascara = m.groups()
    return f"{ip}/{prefijo}" if prefijo else f"{ip} {mascara}"


def _numeros_fuera_de_la_red(texto: str) -> list[int]:
    """Números que no son parte de la red ni la cantidad de subredes ("3 subredes" no son hosts)."""
    limpio = _RED.sub(" ", texto)
    limpio = re.sub(_IP, " ", limpio)
    limpio = re.sub(r"\b\d+\s+(?:sub)?redes\b", " ", limpio, flags=re.IGNORECASE)
    return [int(n) for n in re.findall(r"\b\d+\b", limpio)]


_IP_SOLA = re.compile(rf"\b({_IP})\b")
_PREGUNTA_TIPO_IP = re.compile(r"\b(p[uú]blica|privada|tipo|clase|loopback|apipa|cgnat)\b", re.IGNORECASE)


def decidir_por_reglas(pregunta: str) -> Decision | None:
    texto = pregunta.strip()
    if _SALUDO.match(texto):
        return Decision(tipo="directa", origen="regla", razon="saludo o agradecimiento")

    red = extraer_red(texto)
    if not red:
        ip_sola = _IP_SOLA.search(texto)
        if ip_sola and _PREGUNTA_TIPO_IP.search(texto):   # "¿8.8.8.8 es pública?" -> se analiza como /32
            return Decision(tipo="calculadora", origen="regla", funcion="analizar_red",
                            red=f"{ip_sola.group(1)}/32", razon="IP sola + pregunta por su tipo")
        return None

    minus = texto.lower()
    nube = "aws" if re.search(r"\b(aws|vpc|amazon)\b", minus) else None
    numeros = _numeros_fuera_de_la_red(texto)

    if "vlsm" in minus or (re.search(r"\b(hosts?|equipos|usuarios|computadores)\b", minus) and len(numeros) >= 2):
        return Decision(tipo="calculadora", origen="regla", funcion="vlsm", red=red, hosts=numeros, nube=nube,
                        razon="red + varias cantidades de hosts")
    m = re.search(r"\b(?:en|dividir(?:la)?\s+en|divide(?:la)?\s+en)\s+(\d+)\s+(?:sub)?redes\b", minus)
    if m or re.search(r"\bdivid", minus):
        cantidad = int(m.group(1)) if m else (numeros[0] if numeros else None)
        return Decision(tipo="calculadora", origen="regla", funcion="dividir_en_subredes", red=red,
                        cantidad=cantidad, nube=nube, razon="red + dividir en N subredes")
    return Decision(tipo="calculadora", origen="regla", funcion="analizar_red", red=red, nube=nube,
                    razon="red IPv4 con prefijo o máscara")


# ---------------------------------------------------------------------------
# Etapa 2: modelo por API (OpenRouter, salida con esquema JSON estricto)
# ---------------------------------------------------------------------------

INSTRUCCIONES = """Clasificas preguntas para el asistente de la materia universitaria "Infraestructura de TI".
Temas de la materia: sistemas distribuidos, teorema CAP y PACELC, arquitecturas (centralizada, descentralizada, P2P, híbrida),
modelos de fallo, falacias de la computación distribuida, tiempo y consistencia, comunicación, contenedores y Docker,
Kubernetes, nube y AWS (EC2, VPC, costos), infraestructura como código, redes, seguridad, observabilidad, FinOps,
y datos del curso (créditos, evaluación, horarios, bibliografía).

tipo:
- "calculadora": pide CALCULAR subredes IPv4 con datos concretos (red, cantidad de subredes o de hosts).
- "biblioteca": cualquier pregunta sobre los temas de la materia o el curso, aunque no sepas si hay documentos.
- "directa": saludo, agradecimiento, despedida o preguntas sobre el propio asistente.
- "fuera_de_tema": no tiene relación con la materia (cocina, deportes, farándula, etc.).

Si es "calculadora", llena funcion (analizar_red, dividir_en_subredes o vlsm), red, cantidad, hosts y nube ("aws" solo si
menciona AWS o VPC). Si un campo no aplica usa: funcion "ninguna", red "", cantidad 0, hosts [], nube "ninguna". confianza entre 0 y 1: qué tan seguro estás de que el TIPO elegido es el correcto (no de si la respuesta existe ni de si el tema es fácil). razon: máximo 12 palabras."""

# Esquema sin tipos combinados ni null: es lo que aceptan todos los proveedores en modo estricto.
# Los "vacíos" se representan con valores centinela que el código traduce a None.
ESQUEMA = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": list(TIPOS)},
        "funcion": {"type": "string", "enum": [*FUNCIONES, "ninguna"]},
        "red": {"type": "string", "description": "vacío si no aplica"},
        "cantidad": {"type": "integer", "description": "0 si no aplica"},
        "hosts": {"type": "array", "items": {"type": "integer"}, "description": "vacío si no aplica"},
        "nube": {"type": "string", "enum": ["aws", "ninguna"]},
        "confianza": {"type": "number"},
        "razon": {"type": "string"},
    },
    "required": ["tipo", "funcion", "red", "cantidad", "hosts", "nube", "confianza", "razon"],
    "additionalProperties": False,
}


def desde_centinelas(datos: dict) -> dict:
    """'ninguna', '', 0 y [] significan 'no aplica' -> None."""
    d = dict(datos)
    d["funcion"] = None if d.get("funcion") in ("ninguna", "", None) else d["funcion"]
    d["nube"] = None if d.get("nube") in ("ninguna", "", None) else d["nube"]
    d["red"] = (d.get("red") or "").strip() or None
    d["cantidad"] = d.get("cantidad") or None
    d["hosts"] = d.get("hosts") or None
    return d


def validar_salida(datos: dict) -> dict:
    """Valida el JSON del modelo aunque la API prometa respetar el esquema (defensa en profundidad)."""
    if datos.get("tipo") not in TIPOS:
        raise ValueError(f"tipo inválido: {datos.get('tipo')!r}")
    if datos.get("funcion") not in (*FUNCIONES, None):
        raise ValueError(f"función inválida: {datos.get('funcion')!r}")
    confianza = datos.get("confianza")
    if not isinstance(confianza, (int, float)) or not 0 <= confianza <= 1:
        raise ValueError(f"confianza inválida: {confianza!r}")
    hosts = datos.get("hosts")
    if hosts is not None and not (isinstance(hosts, list) and all(isinstance(h, int) for h in hosts)):
        raise ValueError(f"hosts inválidos: {hosts!r}")
    return datos


class ClienteRecepcionista:
    def __init__(self, api_key: str | None = None, modelos: list[str] | None = None, timeout: float = 15):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.modelos = modelos or [MODELO_PRINCIPAL, MODELO_RESPALDO]
        self.http = httpx.Client(timeout=timeout)

    def clasificar(self, pregunta: str) -> Decision:
        if not self.api_key:
            raise RuntimeError("Falta OPENROUTER_API_KEY en el archivo .env")
        cuerpo = {
            "models": self.modelos,                          # OpenRouter prueba en orden si uno falla
            "messages": [{"role": "system", "content": INSTRUCCIONES},
                         {"role": "user", "content": pregunta}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "decision", "strict": True, "schema": ESQUEMA}},
            "provider": {"require_parameters": True},        # solo proveedores que respeten el esquema
            "reasoning": {"effort": "low"},
            "temperature": 0,
            "max_tokens": 600,                                  # margen por si razona un poco
            "usage": {"include": True},                      # para registrar el costo real
        }
        t0 = time.perf_counter()
        r = self.http.post("https://openrouter.ai/api/v1/chat/completions", json=cuerpo,
                           headers={"Authorization": f"Bearer {self.api_key}", "X-Title": "agente-infra"})
        if r.status_code >= 400:   # el cuerpo trae el motivo real (llave, parámetro, proveedor…)
            raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:400]}")
        datos = r.json()
        latencia = (time.perf_counter() - t0) * 1000
        if "error" in datos:       # OpenRouter a veces responde 200 con un error del proveedor
            raise RuntimeError(f"OpenRouter: {str(datos['error'])[:400]}")
        contenido = datos["choices"][0]["message"].get("content") or ""
        if not contenido.strip():
            raise RuntimeError("OpenRouter devolvió una respuesta vacía (¿se gastó los tokens razonando?)")
        salida = validar_salida(desde_centinelas(json.loads(contenido)))
        return Decision(
            tipo=salida["tipo"], origen=f"modelo:{datos.get('model', '?')}", funcion=salida["funcion"],
            red=salida["red"], cantidad=salida["cantidad"], hosts=salida["hosts"], nube=salida["nube"],
            confianza=float(salida["confianza"]), razon=salida["razon"], latencia_ms=latencia,
            costo_usd=(datos.get("usage") or {}).get("cost"),
        )


# ---------------------------------------------------------------------------
# Decisión completa
# ---------------------------------------------------------------------------

def decidir(pregunta: str, cliente: ClienteRecepcionista | None, solo_modelo: bool = False) -> Decision:
    if not solo_modelo:
        por_reglas = decidir_por_reglas(pregunta)
        if por_reglas:
            return por_reglas
    if cliente is None:
        return Decision(tipo="biblioteca", origen="respaldo", confianza=0.0, razon="sin recepcionista por API")
    try:
        decision = cliente.clasificar(pregunta)
    except Exception as e:  # red caída, API sin saldo, JSON inválido...
        return Decision(tipo="biblioteca", origen="respaldo", confianza=0.0,
                        razon="falló el recepcionista por API", extra={"error": f"{type(e).__name__}: {e}"[:300]})
    if decision.confianza < CONFIANZA_MINIMA and decision.tipo != "biblioteca":
        decision.extra["tipo_original"] = decision.tipo
        decision.tipo, decision.razon = "biblioteca", f"confianza baja ({decision.confianza:.2f}): {decision.razon}"
    if decision.tipo == "calculadora" and not decision.red:
        decision.red = extraer_red(pregunta)     # el modelo detectó el cálculo; la regla intenta la red
    return decision
