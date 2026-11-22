"""Pruebas de la limpieza y el troceo del corpus. Ejecutar con:  python -m pytest -v"""

from rag.ingesta import contar_palabras, limpiar_paginas, trocear, unir_letras_espaciadas


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
