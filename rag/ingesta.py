"""
Ingesta del corpus: convierte los documentos de la carpeta corpus/ en fragmentos
("fichas") listos para indexar, cada uno con su fuente (documento, página, sección).

Uso:
    python -m rag.ingesta                      # lee corpus/ y escribe datos/fragmentos.jsonl
    python -m rag.ingesta --corpus otra/carpeta --salida otro.jsonl

Formatos soportados:
    .pdf   -> un fragmento por página (o varios si la página es larga)
    .md    -> un fragmento por sección (títulos # / ##)
    .xlsx  -> un fragmento por fila de la hoja «Catálogo» (bibliografía)

Cada documento debe estar registrado en corpus/fuentes.csv (título, autor, año...).
Si un archivo no está registrado, se avisa y se omite: así ninguna respuesta del
bot cita una fuente sin título ni autor.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

MAX_PALABRAS = 220    # tamaño máximo de un fragmento
SOLAPE = 40           # palabras que se repiten entre fragmentos consecutivos de la misma página
MIN_PALABRAS = 25     # páginas con menos palabras se tratan como portada o separador de sección


# ---------------------------------------------------------------------------
# Limpieza de texto
# ---------------------------------------------------------------------------

_ESPACIADO = re.compile(r"(?<!\S)(?:\S ){2,}\S(?!\S)")   # 3 o más letras sueltas: "G U Í A"
_SEGMENTO_ESPACIADO = re.compile(r"^(?:\S ){1,}\S$")        # segmento completo de letras sueltas
_SOLO_NUMERO = re.compile(r"^(?:Página\s+)?\d{1,3}$")     # número de página suelto o "Página 3"


def unir_letras_espaciadas(linea: str) -> str:
    """
    'P E R F I L  A  D E S A R R O L L A R' -> 'PERFIL A DESARROLLAR'.
    Los títulos de las diapositivas usan letras espaciadas: dentro de una palabra hay
    un espacio entre letras y entre palabras hay dos o más.
    """
    segmentos = re.split(r"\s{2,}", linea.strip())
    unidos = [
        s.replace(" ", "") if _SEGMENTO_ESPACIADO.match(s)          # "L A" -> "LA"
        else _ESPACIADO.sub(lambda m: m.group().replace(" ", ""), s)  # "T i p o l o g í a Teórica"
        for s in segmentos
    ]
    return " ".join(s for s in unidos if s)


def lineas_repetidas(paginas: list[list[str]], umbral: float = 0.5) -> set[str]:
    """Encabezados y pies de página: líneas que aparecen en al menos la mitad de las páginas."""
    if len(paginas) < 3:
        return set()
    conteo = collections.Counter(l for lineas in paginas for l in set(lineas) if len(l) > 3)
    return {l for l, n in conteo.items() if n / len(paginas) >= umbral}


def limpiar_paginas(paginas_crudas: list[str]) -> list[str]:
    """Quita encabezados/pies repetidos, números de página sueltos y espacios de sobra."""
    paginas = [[unir_letras_espaciadas(l) for l in p.splitlines()] for p in paginas_crudas]
    paginas = [[l for l in p if l] for p in paginas]
    repetidas = lineas_repetidas(paginas)
    limpias = []
    for lineas in paginas:
        utiles = [l for l in lineas if l not in repetidas and not _SOLO_NUMERO.match(l)]
        limpias.append("\n".join(re.sub(r"\s+", " ", l) for l in utiles).strip())
    return limpias


def contar_palabras(texto: str) -> int:
    return len(texto.split())


# ---------------------------------------------------------------------------
# Troceo
# ---------------------------------------------------------------------------

def trocear(texto: str, max_palabras: int = MAX_PALABRAS, solape: int = SOLAPE) -> list[str]:
    """
    Corta un texto en trozos de hasta max_palabras sin partir líneas.
    Cada trozo nuevo arranca con las últimas ~solape palabras del anterior, para no
    perder ideas que quedan justo en el corte.
    """
    lineas = [l for l in texto.splitlines() if l.strip()]
    trozos, actual = [], []
    for linea in lineas:
        palabras_linea = contar_palabras(linea)
        if actual and contar_palabras(" ".join(actual)) + palabras_linea > max_palabras:
            trozos.append("\n".join(actual))
            cola, n = [], 0
            for l in reversed(actual):  # tomar líneas del final hasta cubrir el solape
                if n >= solape:
                    break
                cola.insert(0, l)
                n += contar_palabras(l)
            actual = cola if n < max_palabras else []
        actual.append(linea)
    if actual:
        trozos.append("\n".join(actual))
    return trozos


# ---------------------------------------------------------------------------
# Lectores por formato. Cada uno devuelve una lista de (pagina, seccion, texto).
# ---------------------------------------------------------------------------

_TITULO_SUBNIVEL = re.compile(r"^\d+\.\d+\.?\s+[A-ZÁÉÍÓÚÑ¿]")   # "2.5 Crear el par de claves"
_TITULO_NIVEL1 = re.compile(r"^\d+\.\s+[A-ZÁÉÍÓÚÑ¿]")            # "1. Guía conceptual"


_SEPARADOR_BLOQUE = re.compile(r"^(?:[IVX]+\s+)?BLOQUE\s+\d")


def es_titulo_numerado(linea: str) -> bool:
    """
    Distingue títulos numerados de pasos de lista y celdas de tabla.
    - "2.5 Crear el par de claves" -> título (subnivel), si es corto.
    - "1. Guía conceptual"         -> título: corto y sin punto final.
    - "1. Selecciona Create security group." -> paso de lista (termina en punto).
    - "1 Latencia"                 -> ítem de una diapositiva (sin punto tras el número).
    """
    palabras = len(linea.split())
    if _TITULO_SUBNIVEL.match(linea):
        return palabras <= 10
    if _TITULO_NIVEL1.match(linea):
        return palabras <= 7 and not linea.rstrip().endswith(".")
    return False


def leer_pdf(ruta: Path) -> list[tuple[int | None, str | None, str]]:
    from pypdf import PdfReader

    crudas = [p.extract_text() or "" for p in PdfReader(ruta).pages]
    paginas = limpiar_paginas(crudas)

    bloques, seccion = [], None
    for num, texto in enumerate(paginas, start=1):
        if contar_palabras(texto) < MIN_PALABRAS:
            # Portada o separador ("PARTE I · Qué es un sistema distribuido"): se usa como sección
            if texto:
                seccion = " ".join(texto.split())[:120]
            continue
        # Separador de bloque con contenido ("II BLOQUE 2 · FALACIAS ..."): abre sección y se indexa
        if _SEPARADOR_BLOQUE.match(texto):
            seccion = " ".join(texto.split())[:120]
        # Si la página tiene un título numerado ("1. Guía conceptual"), se actualiza la sección
        for linea in texto.splitlines():
            if es_titulo_numerado(linea):
                seccion = linea
                break
        bloques.append((num, seccion, texto))
    return bloques


def leer_markdown(ruta: Path) -> list[tuple[int | None, str | None, str]]:
    bloques, seccion, actual = [], None, []
    titulo_doc = None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", linea)
        if m:
            if actual and "".join(actual).strip():
                bloques.append((None, seccion, "\n".join(actual).strip()))
            actual = []
            if m.group(1) == "#":
                titulo_doc = m.group(2).strip()
                seccion = None
            else:
                seccion = m.group(2).strip()
            continue
        actual.append(linea)
    if actual and "".join(actual).strip():
        bloques.append((None, seccion, "\n".join(actual).strip()))
    # La introducción (antes del primer ##) queda con la sección = título del documento
    bloques = [(p, s or titulo_doc, t) for p, s, t in bloques]

    # Secciones muy cortas (p. ej. una infografía) se agrupan hasta ~120 palabras,
    # para que cada ficha tenga suficiente contexto. El título de cada sección queda en el texto.
    agrupados, secciones, textos = [], [], []
    for _, s, t in bloques:
        secciones.append(s)
        textos.append(f"{s}:\n{t}" if s else t)
        if contar_palabras(" ".join(textos)) >= 120:
            agrupados.append((None, " / ".join(secciones), "\n\n".join(textos)))
            secciones, textos = [], []
    if textos:
        if agrupados and contar_palabras(" ".join(textos)) < 40:   # un resto pequeño se une al anterior
            _, s_prev, t_prev = agrupados.pop()
            agrupados.append((None, " / ".join([s_prev, *secciones]), "\n\n".join([t_prev, *textos])))
        else:
            agrupados.append((None, " / ".join(secciones), "\n\n".join(textos)))
    return agrupados


def leer_catalogo_xlsx(ruta: Path) -> list[tuple[int | None, str | None, str]]:
    """Una ficha por libro/estándar de la hoja «Catálogo». 'pagina' guarda el número de fila."""
    import openpyxl

    hoja = openpyxl.load_workbook(ruta, data_only=True, read_only=True)["Catálogo"]
    filas = list(hoja.iter_rows(values_only=True))
    encabezado = [str(c) for c in filas[0]]
    campos = ["Título", "Autores", "Año", "Edición", "Editorial / Organismo", "Idioma", "Nivel",
              "Descripción", "Por qué importa (justificación)", "Referencia APA"]
    bloques = []
    for n, fila in enumerate(filas[1:], start=2):
        dato = dict(zip(encabezado, fila))
        if not dato.get("Título"):
            continue
        texto = "\n".join(f"{c}: {dato[c]}" for c in campos if dato.get(c) not in (None, ""))
        bloques.append((n, dato.get("Tema"), texto))
    return bloques


LECTORES = {".pdf": leer_pdf, ".md": leer_markdown, ".xlsx": leer_catalogo_xlsx}


# ---------------------------------------------------------------------------
# Proceso principal
# ---------------------------------------------------------------------------

def leer_fuentes(ruta_csv: Path) -> dict[str, dict]:
    with ruta_csv.open(encoding="utf-8") as f:
        return {fila["archivo"]: fila for fila in csv.DictReader(f)}


def referencia(meta: dict, pagina: int | None, seccion: str | None, extension: str) -> str:
    """Texto de la cita que mostrará el bot, por ejemplo: 'Taller CAP… (Garavito, 2026), pág. 3'."""
    cita = f"{meta['titulo']} ({meta['autor']}, {meta['anio']})"
    if pagina is not None:
        cita += f", fila {pagina}" if extension == ".xlsx" else f", pág. {pagina}"
    if seccion:
        cita += f" – {seccion_corta(seccion)}"
    return cita


def seccion_corta(seccion: str, max_caracteres: int = 45) -> str:
    """
    Acorta la sección para la cita: cada carácter de la cita es texto que el modelo
    debe leer en CPU, y se repite en cada ficha del prompt.
    "A / B / C" -> "A";  textos largos se cortan en la última palabra completa + "…".
    """
    s = seccion.split(" / ")[0].strip()
    if len(s) <= max_caracteres:
        return s
    return s[:max_caracteres].rsplit(" ", 1)[0].rstrip(" ·,") + "…"


def ingerir(carpeta: Path) -> list[dict]:
    fuentes = leer_fuentes(carpeta / "fuentes.csv")
    fragmentos = []
    for ruta in sorted(carpeta.iterdir()):
        ext = ruta.suffix.lower()
        if ext not in LECTORES:
            continue
        meta = fuentes.get(ruta.name)
        if meta is None:
            print(f"AVISO: {ruta.name} no está en fuentes.csv; se omite.", file=sys.stderr)
            continue
        for pagina, seccion, texto in LECTORES[ext](ruta):
            for i, trozo in enumerate(trocear(texto)):
                ident = f"{ruta.stem}:{pagina or 0}:{i}"
                fragmentos.append({
                    "id": ident,
                    "hash": hashlib.sha1(trozo.encode()).hexdigest()[:12],
                    "archivo": ruta.name,
                    "titulo": meta["titulo"],
                    "autor": meta["autor"],
                    "anio": meta["anio"],
                    "pagina": pagina,
                    "seccion": seccion,
                    "cita": referencia(meta, pagina, seccion, ext),
                    "texto": trozo,
                    # Lo que se convierte en embedding: el contexto del documento ayuda a encontrarlo
                    "texto_para_embedding": f"passage: {meta['titulo']}. {seccion or ''}\n{trozo}",
                    "palabras": contar_palabras(trozo),
                })
    return fragmentos


def main() -> None:
    parser = argparse.ArgumentParser(description="Convierte el corpus en fragmentos citables.")
    parser.add_argument("--corpus", default="corpus", type=Path)
    parser.add_argument("--salida", default="datos/fragmentos.jsonl", type=Path)
    args = parser.parse_args()

    fragmentos = ingerir(args.corpus)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        for frag in fragmentos:
            f.write(json.dumps(frag, ensure_ascii=False) + "\n")

    por_doc = collections.defaultdict(list)
    for frag in fragmentos:
        por_doc[frag["archivo"]].append(frag["palabras"])
    print(f"{'Documento':<48} {'Fragmentos':>10} {'Palabras prom.':>15}")
    for doc, palabras in por_doc.items():
        print(f"{doc:<48} {len(palabras):>10} {sum(palabras) / len(palabras):>15.0f}")
    print(f"\nTotal: {len(fragmentos)} fragmentos -> {args.salida}")


if __name__ == "__main__":
    main()
