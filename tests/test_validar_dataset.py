from entrenamiento.validar import problemas_citas, problemas_formato, problemas_fuentes, problemas_numeros

BUENA = ("**La respuesta técnica:** CAP obliga a elegir entre C y A durante una partición.\n"
         "**En lenguaje fácil (pa' que me entiendas):** Como pareja sin WhatsApp.\n"
         "**📚 Fuentes:** Teorema CAP (infografía 2/3) (Solangie Paola Garavito, 2026)")


def test_formato_correcto():
    assert problemas_formato(BUENA, "biblioteca") == []


def test_formato_incorrecto():
    assert problemas_formato("**La respuesta técnica:** hola", "biblioteca")
    desordenada = "**📚 Fuentes:** x\n**La respuesta técnica:** y\n**En lenguaje fácil (pa' que me entiendas):** z"
    assert "secciones fuera de orden" in problemas_formato(desordenada, "biblioteca")
    assert problemas_formato("palabra " * 200, "directa")


def test_fuentes():
    todos = {"Teorema CAP (infografía 2/3)", "Guía AWS"}
    assert problemas_fuentes(BUENA, {"Teorema CAP (infografía 2/3)"}, todos, True) == []
    assert problemas_fuentes(BUENA, {"Guía AWS"}, todos, True)                    # cita algo que no le dieron
    sin_cita = BUENA.replace("Teorema CAP (infografía 2/3)", "un documento")
    assert "responde pero no cita ninguna ficha" in problemas_fuentes(sin_cita, {"Guía AWS"}, todos, True)
    assert problemas_fuentes(sin_cita, {"Guía AWS"}, todos, False) == []          # abstención: puede no citar


def test_numeros_inventados():
    resultado = "Red: 10.0.0.0/26 | Hosts útiles: 62 | Rango: 10.0.0.1 – 10.0.0.62"
    assert problemas_numeros("Tienes 62 hosts en la /26, de 10.0.0.1 a 10.0.0.62", resultado, "analiza 10.0.0.0/26") == []
    assert problemas_numeros("Tienes 64 hosts útiles", resultado, "analiza 10.0.0.0/26")


def test_citas_textuales_exactas():
    fichas = "Estar dentro de una red privada no convierte una\n comunicación en segura. Usa “MyKey.pem” así."
    ok = "Dice que «Estar dentro de una red privada no convierte una comunicación en segura» y «Usa \"MyKey.pem\" así»."
    assert problemas_citas(ok, fichas, minimo=1) == []
    malo = "Dice que «la red privada es totalmente segura»."
    assert problemas_citas(malo, fichas, minimo=1)
    assert "faltan citas textuales (tiene 0, mínimo 1)" in problemas_citas("Sin citas.", fichas, minimo=1)


def test_ip_de_la_pregunta_sin_prefijo_es_valida():
    resultado = "Red: 172.20.0.0/20  |  Hosts útiles: 4094"
    assert problemas_numeros("La IP 172.20.14.77 está en 172.20.0.0/20", resultado, "analiza 172.20.14.77/20") == []
