"""
Convierte un PDF a Markdown con marcas de página, para meterlo al corpus.

Por qué: pypdf (el lector del servidor) no pudo con algunas páginas del libro de Google
(LimitReachedError) y además pega mal las palabras ("W AREHOUSE", "con- sensus").
PyMuPDF extrae mejor: respeta títulos, tablas y palabras. Convertir una vez y guardar
el .md en el repo tiene otra ventaja: el texto que lee el bot queda a la vista y se puede revisar.

Uso (en un PC; el servidor NO necesita esta librería):
    pip install pymupdf4llm
    python scripts/pdf_a_markdown.py libro.pdf corpus/libro.md --titulo "Título del libro"

Formato de salida (lo entiende rag/ingesta.py):
    # Título
    <!-- pagina: 1 -->
    ## Sección
    texto de la página 1...
    <!-- pagina: 2 -->
    ...
Se convierten TODAS las páginas; cuáles se indexan lo decide la columna "paginas" de fuentes.csv.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.ingesta import lineas_repetidas  # noqa: E402  (misma regla de encabezados que la ingesta)

_TITULO = re.compile(r"^(#{1,6})\s+(.*)$")
_SOLO_NUMERO = re.compile(r"^\s*\d{1,4}\s*$")
# Encabezado de página de libro: "1.6 ARCHITECTURAL OVERVIEW OF WSCS 13" o "80 4. DATA CENTER BASICS…"
_ENCABEZADO = re.compile(r"^\s*(\d+\s+)?[\d.]*\s*[A-Z][A-Z0-9 ,:;&()'’\-–.]{6,}?(\s+\d+)?\s*$")
_TEXTO_DE_FIGURA = re.compile(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", re.S)


def limpiar_linea(linea: str) -> str:
    linea = linea.replace("-<br>", "").replace("<br>", " ")          # celdas de tablas
    linea = linea.replace("**", "")                                    # negritas
    linea = re.sub(r"</?(?:mark|span|sup|sub|u|b|i|em|strong)\b[^>]*>", "", linea)  # etiquetas HTML sueltas
    linea = re.sub(r"(?<![\w*])_(\S(?:.*?\S)?)_(?![\w*])", r"\1", linea)  # cursivas _así_
    linea = re.sub(r"(\w)- (\w)", r"\1\2", linea) if re.search(r"\w- [a-z]", linea) else linea
    return linea.rstrip()


def pagina_a_markdown(texto: str) -> list[str]:
    # Las etiquetas sueltas dentro de un gráfico ("OREGON 3 TOKYO…") no son prosa; el pie de figura sí se queda
    texto = _TEXTO_DE_FIGURA.sub("", texto)
    lineas = texto.splitlines()
    primera = next((i for i, l in enumerate(lineas) if l.strip()), None)
    if primera is not None and not lineas[primera].lstrip().startswith("#"):
        limpia = limpiar_linea(lineas[primera]).lstrip("# ").strip()
        if _ENCABEZADO.match(limpia) and re.search(r"\d\s*$|^\d", limpia):
            lineas = lineas[primera + 1:]                              # encabezado de página con número
    salida = []
    for linea in lineas:
        if "intentionally omitted" in linea or linea.strip().startswith("![]("):
            continue                                                   # marcadores de imágenes
        m = _TITULO.match(linea)
        if m:                                                          # todo título queda como sección
            titulo = limpiar_linea(m.group(2)).strip()
            if titulo:
                salida.append(f"## {titulo}")
            continue
        salida.append(limpiar_linea(linea))
    return salida


def convertir(pdf: Path, titulo: str) -> str:
    import pymupdf4llm

    paginas = pymupdf4llm.to_markdown(str(pdf), page_chunks=True, show_progress=False)
    lineas_por_pagina = [pagina_a_markdown(p["text"]) for p in paginas]
    repetidas = lineas_repetidas([[l.strip() for l in ls if l.strip()] for ls in lineas_por_pagina])

    partes = [f"# {titulo}", ""]
    for numero, lineas in enumerate(lineas_por_pagina, start=1):
        partes.append(f"<!-- pagina: {numero} -->")
        for l in lineas:
            if l.strip() in repetidas or _SOLO_NUMERO.match(l):
                continue
            partes.append(l)
        partes.append("")
    texto = "\n".join(partes)
    return re.sub(r"\n{3,}", "\n\n", texto)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("salida", type=Path)
    parser.add_argument("--titulo", required=True)
    args = parser.parse_args()
    args.salida.write_text(convertir(args.pdf, args.titulo), encoding="utf-8")
    n = args.salida.read_text(encoding="utf-8").count("<!-- pagina:")
    print(f"Listo: {args.salida} ({n} páginas)")


if __name__ == "__main__":
    main()
