"""
Arma el dataset de fine-tuning a partir de los ejemplos escritos a mano en entrenamiento/ejemplos/*.jsonl.

    python -m entrenamiento.construir_dataset --ver B014     # muestra las fichas que recibe un ejemplo
    python -m entrenamiento.construir_dataset               # valida todo y escribe entrenamiento/dataset/

Cada línea de un archivo de ejemplos:
    {"id": "B001", "tipo": "biblioteca", "pregunta": "...", "semilla": "<id de ficha>", "respuesta": "..."}
    {"id": "A001", "tipo": "abstencion", "pregunta": "...", "semilla": "<id de ficha a QUITAR>" | null, "respuesta": "..."}
    {"id": "C001", "tipo": "calculadora", "pregunta": "...", "funcion": "...", "red": "...",
     "cantidad": null, "hosts": null, "nube": null, "respuesta": "..."}
    {"id": "D001", "tipo": "directa", "pregunta": "...", "respuesta": "..."}

Contexto de cada ejemplo (4 fichas, como en producción; formato RAFT):
    biblioteca   la ficha semilla + 3 distractores parecidos (BM25), en una posición variable
    abstencion   4 fichas parecidas SIN la página de la semilla: la respuesta no está
Ninguna ficha de las páginas reservadas para evaluación entra en el contexto (separación contra fuga).

Nota: aquí los distractores se eligen con BM25 (léxico) porque los embeddings e5 no están
disponibles en el entorno donde se arma el dataset. En producción el buscador es e5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from agente import presentacion
from agente.agente import ejecutar_calculadora
from agente.recepcionista import Decision
from entrenamiento import validar
from rag.evaluar_busqueda import cargar_preguntas, clave
from rag.prompts import (SISTEMA, SISTEMA_CALCULADORA, SISTEMA_DIRECTA, construir_mensajes,
                         construir_mensajes_calculadora, construir_mensajes_directa)

SEMILLA = 2026
RUTA_FICHAS = Path("datos/fragmentos.jsonl")
RUTA_EVAL = Path("evaluacion/preguntas_busqueda.csv")
CARPETA_EJEMPLOS = Path("entrenamiento/ejemplos")
UMBRAL_TEXTO_FUGA = 0.5
_STOP = set("de la el en y a los las un una que es por con para se del al lo su no o como más sus le ya pero si "
            "este esta ser son entre cada puede qué cómo por qué cuál mi me te tu yo hay muy sin".split())


def tokens(texto: str) -> list[str]:
    return [w for w in re.findall(r"[a-záéíóúñü0-9]{3,}", texto.lower()) if w not in _STOP]


class BM25:
    def __init__(self, fichas: list[dict], k1: float = 1.5, b: float = 0.75):
        self.fichas, self.k1, self.b = fichas, k1, b
        self.docs = [Counter(tokens(f["texto"])) for f in fichas]
        self.largo_medio = sum(sum(d.values()) for d in self.docs) / len(self.docs)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def buscar(self, consulta: str, excluir: set[str], n: int) -> list[dict]:
        q = tokens(consulta)
        puntajes = []
        for f, d in zip(self.fichas, self.docs):
            if clave(f) in excluir:
                continue
            largo = sum(d.values())
            s = sum(self.idf.get(t, 0) * d[t] * (self.k1 + 1) / (d[t] + self.k1 * (1 - self.b + self.b * largo / self.largo_medio))
                    for t in q if t in d)
            puntajes.append((s, f["id"], f))
        puntajes.sort(key=lambda x: (-x[0], x[1]))
        return [f for _, _, f in puntajes[:n]]


def rng_de(id_ejemplo: str) -> random.Random:
    return random.Random(int(hashlib.md5(f"{SEMILLA}:{id_ejemplo}".encode()).hexdigest(), 16))


def ngramas(texto: str, n: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", texto.lower())
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


class Armador:
    def __init__(self):
        self.fichas = [json.loads(l) for l in RUTA_FICHAS.open(encoding="utf-8")]
        self.por_id = {f["id"]: f for f in self.fichas}
        preguntas_eval = cargar_preguntas(RUTA_EVAL)
        self.reservadas = {s for p in preguntas_eval for s in p["validas"]}
        self.ngr_eval = [(p["id"], ngramas(p["pregunta"])) for p in preguntas_eval]
        self.bm25 = BM25(self.fichas)
        self.titulos = {f["titulo"] for f in self.fichas}

    def contexto(self, ej: dict) -> list[dict]:
        semilla = self.por_id.get(ej.get("semilla") or "")
        excluir = set(self.reservadas)
        if semilla:
            excluir.add(clave(semilla))
        if ej["tipo"] == "abstencion":
            fichas = self.bm25.buscar(ej["pregunta"], excluir, 4)
        else:
            fichas = self.bm25.buscar(ej["pregunta"] + " " + semilla["texto"][:300], excluir, 3)
            rng = rng_de(ej["id"])
            posicion = 0 if rng.random() < 0.5 else rng.randint(1, 3)   # la mitad de las veces, primera
            fichas.insert(posicion, semilla)
        return [{**f, "posicion": i} for i, f in enumerate(fichas, start=1)]

    def armar(self, ej: dict) -> tuple[dict | None, list[str]]:
        tipo, pregunta, respuesta = ej["tipo"], ej["pregunta"], ej.get("respuesta", "")
        problemas = []
        if ej.get("semilla") and ej["semilla"] not in self.por_id:
            return None, [f"semilla inexistente: {ej['semilla']}"]
        if ej.get("semilla") and clave(self.por_id[ej["semilla"]]) in self.reservadas:
            return None, ["la semilla es una página reservada para evaluación"]

        if tipo in ("biblioteca", "abstencion"):
            fichas = self.contexto(ej)
            mensajes = construir_mensajes(pregunta, fichas)
            texto_fuente = " ".join(f["texto"] for f in fichas)
            problemas += validar.problemas_formato(respuesta, tipo)
            problemas += validar.problemas_fuentes(respuesta, {f["titulo"] for f in fichas}, self.titulos,
                                                   tiene_respuesta=(tipo == "biblioteca"))
            problemas += validar.problemas_citas(respuesta, texto_fuente, minimo=1 if tipo == "biblioteca" else 0)
            meta = {"fichas": [f["id"] for f in fichas]}
        elif tipo == "calculadora":
            d = Decision(tipo="calculadora", origen="dataset", funcion=ej["funcion"], red=ej["red"],
                         cantidad=ej.get("cantidad"), hosts=ej.get("hosts"), nube=ej.get("nube"))
            resultado = presentacion.resultado_calculadora(ej["funcion"], ejecutar_calculadora(d))
            mensajes = construir_mensajes_calculadora(pregunta, resultado)
            problemas += validar.problemas_formato(respuesta, tipo)
            problemas += validar.problemas_numeros(respuesta, resultado, pregunta)
            problemas += validar.problemas_citas(respuesta, resultado, minimo=1)
            meta = {"funcion": ej["funcion"]}
        else:
            mensajes = construir_mensajes_directa(pregunta)
            problemas += validar.problemas_formato(respuesta, "directa")
            meta = {}

        fuga = max(len(ngramas(pregunta) & n) / len(ngramas(pregunta) | n) for _, n in self.ngr_eval)
        if fuga > UMBRAL_TEXTO_FUGA:
            problemas.append(f"pregunta muy parecida a una de evaluación (texto {fuga:.2f})")
        sistema = {"calculadora": SISTEMA_CALCULADORA, "directa": SISTEMA_DIRECTA}.get(tipo, SISTEMA)
        ejemplo = {"id": ej["id"], "tipo": tipo,
                   "messages": [{"role": "system", "content": sistema}, mensajes[1],
                                {"role": "assistant", "content": respuesta.strip()}],
                   "meta": meta}
        return ejemplo, problemas


def cargar_ejemplos() -> list[dict]:
    ejemplos = []
    for ruta in sorted(CARPETA_EJEMPLOS.glob("*.jsonl")):
        for n, linea in enumerate(ruta.open(encoding="utf-8"), start=1):
            if linea.strip():
                try:
                    ejemplos.append(json.loads(linea))
                except json.JSONDecodeError as e:
                    raise SystemExit(f"{ruta}:{n}: JSON inválido: {e}")
    ids = [e["id"] for e in ejemplos]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise SystemExit(f"IDs repetidos: {sorted(repetidos)}")
    return ejemplos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ver", help="muestra el contexto (fichas) de un ejemplo por su id")
    parser.add_argument("--salida", type=Path, default=Path("entrenamiento/dataset"))
    args = parser.parse_args()

    armador, ejemplos = Armador(), cargar_ejemplos()
    if args.ver:
        ej = next(e for e in ejemplos if e["id"] == args.ver)
        if ej["tipo"] == "calculadora":
            d = Decision(tipo="calculadora", origen="dataset", funcion=ej["funcion"], red=ej["red"],
                         cantidad=ej.get("cantidad"), hosts=ej.get("hosts"), nube=ej.get("nube"))
            print(presentacion.resultado_calculadora(ej["funcion"], ejecutar_calculadora(d)))
            return
        if ej["tipo"] == "directa":
            print("(directa: sin contexto)")
            return
        for f in armador.contexto(ej):
            print(f"--- [Ficha {f['posicion']}] {f['id']}\n{f['cita']}\n{' '.join(f['texto'].split())}\n")
        return

    aceptados, rechazados = [], []
    for ej in ejemplos:
        ejemplo, problemas = armador.armar(ej)
        if problemas:
            rechazados.append({"id": ej["id"], "problemas": problemas})
        else:
            aceptados.append(ejemplo)

    for r in rechazados:
        print(f"❌ {r['id']}: {' | '.join(r['problemas'])}")
    conteo = Counter(e["tipo"] for e in aceptados)
    print(f"\nAceptados: {len(aceptados)}  {dict(conteo)}  |  Rechazados: {len(rechazados)}")
    if rechazados:
        print("Corrige los rechazados antes de entrenar.")

    rng = random.Random(SEMILLA)
    rng.shuffle(aceptados)
    n_val = max(1, len(aceptados) // 10)
    args.salida.mkdir(parents=True, exist_ok=True)
    for nombre, filas in (("val", aceptados[:n_val]), ("train", aceptados[n_val:])):
        with (args.salida / f"{nombre}.jsonl").open("w", encoding="utf-8") as f:
            for fila in filas:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    reporte = {"aceptados": len(aceptados), "por_tipo": dict(conteo), "train": len(aceptados) - n_val,
               "val": n_val, "rechazados": rechazados, "paginas_reservadas": len(armador.reservadas),
               "redaccion": "Ejemplos redactados con asistencia de Claude (Anthropic) y revisados por el estudiante"}
    (args.salida / "reporte.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Escrito en {args.salida}/ (train {reporte['train']}, val {n_val})")


if __name__ == "__main__":
    main()
