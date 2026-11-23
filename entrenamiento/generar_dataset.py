# ⚠️ OBSOLETO (no se usó para el dataset final). Se conserva solo como registro de la alternativa
# descartada: el dataset final se escribió a mano con asistencia de Claude, se revisó por el estudiante
# y se arma con `python -m entrenamiento.construir_dataset`. Los encabezados de respuesta de este
# archivo son los viejos; los vigentes están en rag/prompts.py y entrenamiento/validar.py.
"""
Genera el dataset de fine-tuning (formato RAFT + estilo del bot) con un modelo "profesor".

    docker compose run --rm agente python -m entrenamiento.generar_dataset --profesor <id-openrouter>

Qué genera (cada ejemplo = system + user + assistant, con los MISMOS prompts de producción):
    biblioteca   pregunta de estudiante + 4 fichas recuperadas (con distractores naturales) -> respuesta citada
    abstencion   igual, pero se quitan las fichas que tenían la respuesta -> "no está en mis documentos"
    calculadora  red aleatoria -> resultado exacto de la calculadora -> explicación con humor
    directa      saludos y preguntas sobre el bot -> respuesta breve

Separación contra fuga de datos (decisión D32):
    - Las páginas que responden las preguntas congeladas de evaluación quedan RESERVADAS:
      no se generan preguntas sobre ellas ni aparecen como fichas en ningún ejemplo.
    - Cada pregunta generada se compara con las de evaluación (similitud de significado y de
      texto). Si se parecen demasiado, se descarta.

Salida en entrenamiento/dataset/:
    train.jsonl, val.jsonl   ejemplos aceptados (90 % / 10 %)
    descartados.jsonl        ejemplos rechazados y el motivo
    reporte.json             conteos, costo y parámetros
    revisar.md               muestra aleatoria para revisión humana
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from agente import presentacion
from entrenamiento import validar
from entrenamiento.profesor import ClienteProfesor
from herramientas.calculadora_subredes import ErrorEntrada, analizar_red, dividir_en_subredes, vlsm
from rag.buscador import Buscador
from rag.evaluar_busqueda import cargar_preguntas, clave
from rag.prompts import (SISTEMA, SISTEMA_CALCULADORA, SISTEMA_DIRECTA, construir_mensajes,
                         construir_mensajes_calculadora, construir_mensajes_directa)

SEMILLA = 2026
UMBRAL_SIMILITUD_FUGA = 0.85
UMBRAL_TEXTO_FUGA = 0.5

# ---------------------------------------------------------------------------
# Guía del profesor: se usa SOLO para generar. El modelo entrenado nunca la ve:
# aprende el comportamiento con el prompt corto de producción.
# ---------------------------------------------------------------------------

GUIA_RESPUESTA = SISTEMA + """

GUÍA DE CALIDAD (para ti, que eres el profesor que escribe respuestas de ejemplo):
- Usa EXACTAMENTE estos encabezados, en este orden y con negritas:
  **La respuesta corta:**  /  **En lenguaje fácil (pa' que me entiendas):**  /  **📚 Fuentes:**
- La respuesta corta es técnicamente impecable y se apoya solo en las fichas.
- La analogía es de relaciones humanas (pareja, ex, amigos, familia, roommates, grupo de WhatsApp), con humor ácido
  y colombiano neutro, y sobre todo FIEL al concepto: cada parte de la analogía corresponde a una parte del concepto.
  Prohibido: estereotipos de género o de grupos, groserías, burlas a quien pregunta.
- En Fuentes, copia literalmente la "Fuente" de las fichas que usaste (una por línea, con "- ").
- Si las fichas NO responden la pregunta: tiene_respuesta = false. Di con humor que no está en tus documentos,
  sin inventar nada; si alguna ficha trae algo relacionado y útil, menciónalo y cítalo; si no, en Fuentes escribe
  "Ninguna de mis fichas responde esto."
- Máximo 140 palabras. Variedad: no empieces todas las analogías igual.

EJEMPLO DE ESTILO (no lo copies):
**La respuesta corta:** Cuando la red se parte, un sistema distribuido debe elegir entre responder siempre aunque
el dato esté viejo (A) o responder solo con el dato confirmado y, si no puede, fallar (C).
**En lenguaje fácil (pa' que me entiendas):** Es tu relación a distancia cuando se cae el WhatsApp. Opción C: no
confirmas el plan del sábado hasta hablar con tu pareja. Opción A: dices "sí, vamos" con lo último que sabías…
aunque quizá ya cancelaron. Y no es "dos de tres para siempre": se decide por cada operación.
**📚 Fuentes:**
- Teorema CAP (infografía 2/3) (Solangie Paola Garavito, 2026)"""

GUIA_CALCULADORA = SISTEMA_CALCULADORA + """

GUÍA DE CALIDAD: usa exactamente los encabezados **La respuesta corta:**, **En lenguaje fácil (pa' que me entiendas):**
y **📚 Fuentes:**. No calcules nada: usa SOLO números que aparecen en el resultado. La analogía (relaciones humanas,
humor ácido, sin estereotipos) debe reflejar lo que hace la red: repartir direcciones, desperdicio, reservas de AWS,
etc. En Fuentes escribe exactamente: Calculadora de subredes IPv4 (herramienta propia del agente). Máximo 110 palabras."""

GUIA_DIRECTA = SISTEMA_DIRECTA + "\nSin encabezados. Humor ácido amable, sin estereotipos. Máximo 45 palabras."

GUIA_PREGUNTAS = """Eres un estudiante universitario colombiano de Infraestructura de TI.
Lee la ficha y escribe 2 preguntas DISTINTAS que harías y que ESTA ficha responde por completo:
1) una conceptual ("¿qué es…?", "¿por qué…?"), 2) una aplicada a una situación concreta.
Escribe como estudiante real (puede ser informal). NO copies más de 4 palabras seguidas de la ficha.
No menciones "la ficha", "el documento" ni la página. Si la ficha no tiene contenido útil (solo instrucciones de
formato, tablas vacías o datos administrativos sin sustancia), devuelve una lista vacía."""

ESQUEMA_PREGUNTAS = {"type": "object", "properties": {"preguntas": {"type": "array", "items": {"type": "string"}}},
                     "required": ["preguntas"], "additionalProperties": False}
ESQUEMA_RESPUESTA = {"type": "object",
                     "properties": {"tiene_respuesta": {"type": "boolean"}, "respuesta": {"type": "string"}},
                     "required": ["tiene_respuesta", "respuesta"], "additionalProperties": False}
ESQUEMA_TEXTO = {"type": "object", "properties": {"respuesta": {"type": "string"}},
                 "required": ["respuesta"], "additionalProperties": False}

# Temas del curso que NO están en los documentos -> enseñan a abstenerse con preguntas "cercanas".
# Se evitan a propósito los temas de las preguntas negativas de evaluación (Paxos, RTO/RPO, CRDT, kubectl, c7g).
CERCANAS_FUERA_DEL_CORPUS = [
    "¿Cómo creo un bucket de S3 con versionado activado?",
    "¿Qué es un Helm chart y cómo lo instalo en el clúster?",
    "¿Cómo funciona paso a paso el autoscaling horizontal de pods en Kubernetes?",
    "¿Cómo configuro el Collector de OpenTelemetry?",
    "¿Cuánto cuesta al mes una base de datos RDS pequeña?",
    "¿Cuáles son las fases del two-phase commit y qué pasa si el coordinador se cae?",
    "¿Cómo se toma un snapshot de Chandy-Lamport paso a paso?",
    "¿Cómo se calcula el presupuesto de error de un SLO del 99,9 %?",
    "¿Cómo instalo y configuro Argo CD?",
    "¿Qué diferencia hay entre Prometheus y Grafana?",
    "¿Cómo se configura un Application Load Balancer en AWS?",
    "¿Qué es un sidecar en un service mesh como Istio?",
]

DIRECTAS = [
    "hola", "buenas noches", "holi, ¿cómo vas?", "¿quién eres?", "¿qué puedes hacer?", "¿cómo te llamas?",
    "gracias, me sirvió mucho", "¿eres una persona o un bot?", "chao, nos vemos", "¿me ayudas a estudiar para el parcial?",
    "¿de qué temas sabes?", "¿por qué eres tan sarcástico?", "jajaja buenísimo", "¿quién te programó?", "ok, listo",
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def ngramas(texto: str, n: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", texto.lower())
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def paginas_reservadas(ruta_preguntas: Path) -> set[str]:
    return {s for p in cargar_preguntas(ruta_preguntas) for s in p["validas"]}


def ejemplo(tipo: str, mensajes: list[dict], respuesta: str, **meta) -> dict:
    return {"tipo": tipo, "messages": [*mensajes, {"role": "assistant", "content": respuesta.strip()}], "meta": meta}


# ---------------------------------------------------------------------------
# Calculadora: casos aleatorios pero reproducibles
# ---------------------------------------------------------------------------

def casos_calculadora(rng: random.Random, n: int) -> list[tuple[str, str, dict]]:
    plantillas_analizar = ["analiza la red {red}", "¿cuántos hosts útiles tiene {red}?", "dame el rango de {red}",
                           "¿cuál es el broadcast de {red}?", "explícame la red {red} de mi VPC en AWS"]
    plantillas_dividir = ["divide {red} en {n} subredes", "necesito partir {red} en {n} subredes iguales",
                          "divide la {red} de mi VPC de AWS en {n} subredes"]
    plantillas_vlsm = ["haz VLSM de {red} para {h} hosts", "reparte {red} entre grupos de {h} equipos",
                       "vlsm en mi VPC de AWS {red} con {h} hosts"]
    casos = []
    while len(casos) < n:
        tipo = rng.choice(["analizar_red", "dividir_en_subredes", "vlsm"])
        base = rng.choice(["10.{a}.{b}.0", "172.{c}.{b}.0", "192.168.{b}.0", "100.64.{b}.0", "8.{a}.{b}.0"]).format(
            a=rng.randint(0, 255), b=rng.randint(0, 255), c=rng.randint(16, 31))
        try:
            if tipo == "analizar_red":
                plantilla = rng.choice(plantillas_analizar)
                nube = "aws" if "AWS" in plantilla else None
                prefijo = rng.randint(16, 28) if nube else rng.choice([8, 12, 16, 20, 22, 24, 25, 26, 27, 28, 29, 30, 31, 32])
                host = base.rsplit(".", 1)[0] + f".{rng.randint(0, 254)}"
                red = f"{host}/{prefijo}"
                pregunta = plantilla.format(red=red)
                resultado = analizar_red(red, nube=nube)
            elif tipo == "dividir_en_subredes":
                plantilla = rng.choice(plantillas_dividir)
                nube = "aws" if "AWS" in plantilla else None
                red, cantidad = f"{base}/{rng.choice([16, 20, 22, 24])}", rng.randint(2, 12)
                pregunta = plantilla.format(red=red, n=cantidad)
                resultado = dividir_en_subredes(red, cantidad, nube=nube)
            else:
                plantilla = rng.choice(plantillas_vlsm)
                nube = "aws" if "AWS" in plantilla else None
                red = f"{base}/{rng.choice([22, 23, 24])}"
                hosts = sorted(rng.sample([5, 10, 12, 20, 25, 30, 40, 50, 60, 100], rng.randint(2, 4)), reverse=True)
                pregunta = plantilla.format(red=red, h=", ".join(map(str, hosts)))
                resultado = vlsm(red, hosts, nube=nube)
        except ErrorEntrada:
            continue
        casos.append((pregunta, presentacion.resultado_calculadora(tipo, resultado), {"funcion": tipo}))
    return casos


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profesor", required=True, help="ID de OpenRouter del modelo profesor")
    parser.add_argument("--fichas", type=int, default=60, help="fichas sobre las que se generan preguntas")
    parser.add_argument("--abstencion", type=float, default=0.25, help="fracción de preguntas sin su ficha fuente")
    parser.add_argument("--calculadora", type=int, default=30)
    parser.add_argument("--hilos", type=int, default=6)
    parser.add_argument("--salida", type=Path, default=Path("entrenamiento/dataset"))
    args = parser.parse_args()

    rng = random.Random(SEMILLA)
    profesor = ClienteProfesor(args.profesor)
    buscador = Buscador("datos/indice")
    reservadas = paginas_reservadas(Path("evaluacion/preguntas_busqueda.csv"))
    preguntas_eval = [p["pregunta"] for p in cargar_preguntas(Path("evaluacion/preguntas_busqueda.csv"))]
    todos_los_titulos = {f["titulo"] for f in buscador.fragmentos}
    aceptados, descartados = [], []

    def recuperar(pregunta: str, excluir: set[str]) -> list[dict]:
        """Top-4 sin páginas reservadas (ni las excluidas). Se pide más de 4 para poder filtrar."""
        candidatas = buscador.buscar(pregunta, 20)
        fichas = [f for f in candidatas if clave(f) not in reservadas and clave(f) not in excluir][:4]
        for i, f in enumerate(fichas, start=1):
            f["posicion"] = i
        return fichas

    # 1) Preguntas a partir de fichas NO reservadas
    elegibles = [f for f in buscador.fragmentos if clave(f) not in reservadas and f["palabras"] >= 40]
    catalogo = [f for f in elegibles if f["archivo"].endswith(".xlsx")]
    contenido = [f for f in elegibles if not f["archivo"].endswith(".xlsx")]
    n_catalogo = min(len(catalogo), max(4, args.fichas // 8))
    semillas = rng.sample(contenido, min(len(contenido), args.fichas - n_catalogo)) + rng.sample(catalogo, n_catalogo)
    print(f"Páginas reservadas para evaluación: {len(reservadas)}  |  fichas semilla: {len(semillas)} "
          f"({len(semillas) - n_catalogo} de contenido, {n_catalogo} del catálogo)")

    def preguntas_de(ficha: dict) -> list[tuple[str, dict]]:
        usuario = f"FICHA (Fuente: {ficha['cita']}):\n{' '.join(ficha['texto'].split())}"
        salida = profesor.json(GUIA_PREGUNTAS, usuario, ESQUEMA_PREGUNTAS, max_tokens=300)
        return [(p.strip(), ficha) for p in salida["preguntas"][:2] if len(p.strip()) > 10]

    with ThreadPoolExecutor(args.hilos) as pool:
        pares = [par for lista in pool.map(preguntas_de, semillas) for par in lista]
    print(f"Preguntas generadas: {len(pares)}")

    # 2) Filtro contra fuga: similitud de significado y de texto con las preguntas de evaluación
    vec_eval = buscador.codificar([f"query: {q}" for q in preguntas_eval])
    vec_gen = buscador.codificar([f"query: {q}" for q, _ in pares]) if pares else np.zeros((0, 1))
    ngr_eval = [ngramas(q) for q in preguntas_eval]
    limpias = []
    for (pregunta, ficha), v in zip(pares, vec_gen):
        sim = float(np.max(vec_eval @ v))
        txt = max(jaccard(ngramas(pregunta), n) for n in ngr_eval)
        if sim > UMBRAL_SIMILITUD_FUGA or txt > UMBRAL_TEXTO_FUGA:
            descartados.append({"tipo": "pregunta", "pregunta": pregunta,
                                "motivo": f"fuga: similitud {sim:.3f}, texto {txt:.2f}"})
        else:
            limpias.append((pregunta, ficha, sim))
    print(f"Descartadas por parecerse a la evaluación: {len(pares) - len(limpias)}")

    # 3) Respuestas RAG (normales y de abstención)
    trabajos = []
    for pregunta, ficha, sim in limpias:
        abstener = rng.random() < args.abstencion
        excluir = {clave(ficha)} if abstener else set()
        trabajos.append(("abstencion" if abstener else "biblioteca", pregunta, recuperar(pregunta, excluir),
                         {"ficha_fuente": ficha["id"], "sim_max_eval": round(sim, 3)}))
    for pregunta in CERCANAS_FUERA_DEL_CORPUS:
        trabajos.append(("abstencion", pregunta, recuperar(pregunta, set()), {"cercana_fuera_del_corpus": True}))

    def responder_rag(trabajo):
        tipo, pregunta, fichas, meta = trabajo
        mensajes = construir_mensajes(pregunta, fichas)
        salida = profesor.json(GUIA_RESPUESTA, mensajes[1]["content"], ESQUEMA_RESPUESTA)
        tipo_real = "biblioteca" if salida["tiene_respuesta"] else "abstencion"
        titulos = {f["titulo"] for f in fichas}
        problemas = (validar.problemas_formato(salida["respuesta"], tipo_real)
                     + validar.problemas_fuentes(salida["respuesta"], titulos, todos_los_titulos, salida["tiene_respuesta"]))
        meta = {**meta, "pedido": tipo, "fichas": [f["id"] for f in fichas]}
        return ejemplo(tipo_real, [{"role": "system", "content": SISTEMA}, mensajes[1]], salida["respuesta"], **meta), problemas

    # 4) Calculadora
    def responder_calc(caso):
        pregunta, resultado, meta = caso
        mensajes = construir_mensajes_calculadora(pregunta, resultado)
        salida = profesor.json(GUIA_CALCULADORA, mensajes[1]["content"], ESQUEMA_TEXTO)
        problemas = (validar.problemas_formato(salida["respuesta"], "calculadora")
                     + validar.problemas_numeros(salida["respuesta"], resultado, pregunta))
        return ejemplo("calculadora", [{"role": "system", "content": SISTEMA_CALCULADORA}, mensajes[1]],
                       salida["respuesta"], **meta), problemas

    # 5) Directas
    def responder_directa(pregunta):
        mensajes = construir_mensajes_directa(pregunta)
        salida = profesor.json(GUIA_DIRECTA, pregunta, ESQUEMA_TEXTO, max_tokens=200)
        return (ejemplo("directa", [{"role": "system", "content": SISTEMA_DIRECTA}, mensajes[1]], salida["respuesta"]),
                validar.problemas_formato(salida["respuesta"], "directa"))

    tareas = ([(responder_rag, t) for t in trabajos]
              + [(responder_calc, c) for c in casos_calculadora(rng, args.calculadora)]
              + [(responder_directa, d) for d in DIRECTAS])

    def ejecutar(tarea):
        funcion, dato = tarea
        try:
            return funcion(dato)
        except Exception as e:
            return {"tipo": "error", "dato": str(dato)[:200]}, [f"error del profesor: {e}"[:300]]

    with ThreadPoolExecutor(args.hilos) as pool:
        for i, (ej, problemas) in enumerate(pool.map(ejecutar, tareas), start=1):
            (descartados if problemas else aceptados).append({**ej, "problemas": problemas} if problemas else ej)
            if i % 20 == 0:
                print(f"  {i}/{len(tareas)} ejemplos procesados (aceptados {len(aceptados)})")

    # 6) Guardar: train / val, descartados, reporte y muestra para revisión humana
    rng.shuffle(aceptados)
    n_val = max(1, len(aceptados) // 10)
    args.salida.mkdir(parents=True, exist_ok=True)
    for nombre, filas in (("val", aceptados[:n_val]), ("train", aceptados[n_val:]), ("descartados", descartados)):
        with (args.salida / f"{nombre}.jsonl").open("w", encoding="utf-8") as f:
            for fila in filas:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")

    conteo = {}
    for e in aceptados:
        conteo[e["tipo"]] = conteo.get(e["tipo"], 0) + 1
    reporte = {"profesor": args.profesor, "semilla": SEMILLA, "aceptados": len(aceptados), "por_tipo": conteo,
               "train": len(aceptados) - n_val, "val": n_val, "descartados": len(descartados),
               "paginas_reservadas": len(reservadas), "costo_usd": round(profesor.costo_total, 4),
               "umbrales_fuga": {"similitud": UMBRAL_SIMILITUD_FUGA, "texto": UMBRAL_TEXTO_FUGA}}
    (args.salida / "reporte.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")

    muestra = rng.sample(aceptados, min(20, len(aceptados)))
    with (args.salida / "revisar.md").open("w", encoding="utf-8") as f:
        f.write("# Muestra para revisión humana\n\nRevisa: ¿correcta? ¿analogía fiel? ¿humor sin ofender? ¿fuentes bien?\n\n")
        for i, e in enumerate(muestra, start=1):
            pregunta = e["messages"][1]["content"].split("PREGUNTA:")[-1].strip()
            f.write(f"## {i}. [{e['tipo']}] {pregunta[:200]}\n\n{e['messages'][2]['content']}\n\n---\n\n")

    print("\n" + json.dumps(reporte, indent=2, ensure_ascii=False))
    motivos = {}
    for d in descartados:
        for p in d.get("problemas", [d.get("motivo", "?")]):
            motivos[p.split(":")[0]] = motivos.get(p.split(":")[0], 0) + 1
    print("Motivos de descarte:", json.dumps(motivos, ensure_ascii=False))


if __name__ == "__main__":
    main()
