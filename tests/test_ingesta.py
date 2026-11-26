"""Pruebas de la limpieza y el troceo del corpus. Ejecutar con:  python -m pytest -v"""

from rag.ingesta import (contar_palabras, es_titulo_numerado, limpiar_paginas, seccion_corta, trocear,
                         unir_letras_espaciadas)


def test_une_titulos_con_letras_espaciadas():
    assert unir_letras_espaciadas("P E R F I L  A  D E S A R R O L L A R") == "PERFIL A DESARROLLAR"
    assert unir_letras_espaciadas("0 1   L A  A S I G N A T U R A") == "01 LA ASIGNATURA"
    assert unir_letras_espaciadas("T i p o l o g í a Teórica / Práctica") == "Tipología Teórica / Práctica"


def test_no_toca_texto_normal():
    frase = "El sistema y a la vez el nodo responde."
    assert unir_letras_espaciadas(frase) == frase


def test_quita_encabezados_repetidos_y_numeros_de_pagina():
    paginas = [f"ENCABEZADO DEL CURSO\nContenido de la página {i}\n{i}" for i in range(1, 6)]
    limpias = limpiar_paginas(paginas)
    assert all("ENCABEZADO" not in p for p in limpias)
    assert limpias[2] == "Contenido de la página 3"


def test_trocear_respeta_el_maximo_y_solapa():
    texto = "\n".join(f"linea numero {i} con algunas palabras extra" for i in range(100))
    trozos = trocear(texto, max_palabras=50, solape=10)
    assert len(trozos) > 1
    assert all(contar_palabras(t) <= 50 + 7 for t in trozos)   # 7 = palabras de una línea
    # La última línea de un trozo reaparece al inicio del siguiente (solape)
    assert trozos[0].splitlines()[-1] in trozos[1]


def test_trocear_texto_corto_queda_igual():
    assert trocear("una sola línea") == ["una sola línea"]


def test_detecta_titulos_numerados():
    assert es_titulo_numerado("1. Guía conceptual")
    assert es_titulo_numerado("2.5 Crear el par de claves (Key pair)")
    assert es_titulo_numerado("4.5. Verificación de puertos para las conexiones")


def test_no_confunde_pasos_ni_items_con_titulos():
    assert not es_titulo_numerado("1 Latencia")                               # ítem de diapositiva
    assert not es_titulo_numerado("4 La red es segura Seguridad y Zero Trust")  # fila de tabla
    assert not es_titulo_numerado("1. Selecciona Create security group.")      # paso de lista
    assert not es_titulo_numerado("6. Verifica tu identidad por mensaje de texto (SMS")


def test_seccion_corta():
    assert seccion_corta("1. Guía conceptual") == "1. Guía conceptual"
    assert seccion_corta("Teorema CAP (infografía 2/3) / C – Consistencia / A") == "Teorema CAP (infografía 2/3)"
    larga = "BLOQUE 3 · MODELOS DE FALLO Modelos de fallo Tipos de fallo, relación entre causa y efecto"
    corta = seccion_corta(larga)
    assert len(corta) <= 46 and corta.endswith("…") and corta.startswith("BLOQUE 3")


def test_rango_paginas():
    from rag.ingesta import rango_paginas
    assert rango_paginas("") is None and rango_paginas(None) is None
    assert rango_paginas("2, 5-7") == {2, 5, 6, 7}
    import pytest
    with pytest.raises(ValueError):
        rango_paginas("9-3")


def test_pagina_que_falla_no_tumba_la_ingesta(capsys):
    from rag.ingesta import texto_de_pagina

    class PaginaRota:
        def extract_text(self):
            raise RuntimeError("Reached maximum number of tokens per stream.")

    class PaginaBuena:
        def extract_text(self):
            return "hola"

    assert texto_de_pagina(PaginaRota(), "libro.pdf", 33) == ""
    assert "libro.pdf pág. 33" in capsys.readouterr().err
    assert texto_de_pagina(PaginaBuena(), "libro.pdf", 34) == "hola"


def test_markdown_con_paginas_conserva_numero_y_seccion(tmp_path):
    from rag.ingesta import leer_markdown
    relleno = " ".join(["palabra"] * 30)
    md = tmp_path / "libro.md"
    md.write_text(
        "# Libro\n\n"
        "<!-- pagina: 1 -->\nFigura sola\n\n"                        # página corta: pasa a la siguiente
        f"<!-- pagina: 2 -->\n## 1 Introducción\n{relleno}\n\n"
        f"<!-- pagina: 3 -->\n{relleno}\n## 1.1 Detalle\nmás texto\n",
        encoding="utf-8")
    bloques = leer_markdown(md)
    assert [b[0] for b in bloques] == [2, 3]
    assert bloques[0][1] == "1 Introducción" and "Figura sola" in bloques[0][2]
    assert bloques[1][1] == "1 Introducción"        # la pág. 3 empieza continuando la sección 1


def test_markdown_sin_marcas_sigue_igual(tmp_path):
    from rag.ingesta import leer_markdown
    md = tmp_path / "info.md"
    md.write_text("# Info\n\n## A\nuno dos\n\n## B\ntres cuatro\n", encoding="utf-8")
    assert all(b[0] is None for b in leer_markdown(md))
