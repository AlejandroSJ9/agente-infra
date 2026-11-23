"""Pruebas de la calculadora de subredes. Ejecutar con:  python -m pytest -v"""

import pytest

from herramientas.calculadora_subredes import (
    ErrorEntrada, analizar_red, dividir_en_subredes, vlsm,
)


# ----------------------------- analizar_red --------------------------------

def test_red_clase_c_tipica():
    r = analizar_red("192.168.1.10/24")
    assert r["direccion_red"] == "192.168.1.0"
    assert r["broadcast"] == "192.168.1.255"
    assert r["primer_host"] == "192.168.1.1"
    assert r["ultimo_host"] == "192.168.1.254"
    assert r["hosts_utiles"] == 254
    assert r["mascara"] == "255.255.255.0"
    assert r["wildcard"] == "0.0.0.255"
    assert r["tipo"] == "privada (RFC 1918)"
    assert r["clase_historica"] == "C"


def test_acepta_mascara_decimal():
    assert analizar_red("10.0.5.7 255.255.252.0")["red"] == "10.0.4.0/22"
    assert analizar_red("10.0.5.7/255.255.252.0")["red"] == "10.0.4.0/22"


def test_prefijo_no_tipico():
    r = analizar_red("172.16.45.200/27")
    assert r["direccion_red"] == "172.16.45.192"
    assert r["broadcast"] == "172.16.45.223"
    assert r["hosts_utiles"] == 30


def test_caso_limite_31_punto_a_punto():
    r = analizar_red("10.0.0.0/31")
    assert r["hosts_utiles"] == 2
    assert r["broadcast"] is None
    assert "RFC 3021" in r["nota"]


def test_caso_limite_32_un_host():
    r = analizar_red("8.8.8.8/32")
    assert r["hosts_utiles"] == 1
    assert r["tipo"] == "pública"


def test_caso_limite_0():
    r = analizar_red("0.0.0.0/0")
    assert r["total_direcciones"] == 2 ** 32
    assert any("/0" in a for a in r["avisos"])


def test_aviso_si_la_ip_es_la_de_red_o_broadcast():
    assert any("dirección de red" in a for a in analizar_red("192.168.1.0/24")["avisos"])
    assert any("broadcast" in a for a in analizar_red("192.168.1.255/24")["avisos"])


def test_tipos_especiales():
    assert "loopback" in analizar_red("127.0.0.1/8")["tipo"]
    assert "APIPA" in analizar_red("169.254.10.1/16")["tipo"]
    assert "CGNAT" in analizar_red("100.64.1.1/10")["tipo"]


@pytest.mark.parametrize("entrada", [
    "", "   ", "hola", "192.168.1.10",          # vacío / texto / sin máscara
    "256.1.1.1/24", "192.168.1/24",              # octeto > 255 / faltan octetos
    "192.168.1.1/33", "192.168.1.1/-1",          # prefijo fuera de rango
    "192.168.1.1 255.0.255.0",                   # máscara no contigua
    "192.168.01.1/24",                           # ceros a la izquierda
])
def test_entradas_invalidas(entrada):
    with pytest.raises(ErrorEntrada):
        analizar_red(entrada)


# -------------------------- dividir_en_subredes ----------------------------

def test_dividir_en_4():
    r = dividir_en_subredes("192.168.1.0/24", 4)
    assert r["nuevo_prefijo"] == 26
    assert r["hosts_utiles_por_subred"] == 62
    assert [s["red"] for s in r["subredes"]] == [
        "192.168.1.0/26", "192.168.1.64/26", "192.168.1.128/26", "192.168.1.192/26"]


def test_dividir_redondea_a_potencia_de_2():
    r = dividir_en_subredes("192.168.1.0/24", 5)
    assert r["subredes_obtenidas"] == 8
    assert r["avisos"]


def test_dividir_en_1_devuelve_la_misma_red():
    assert dividir_en_subredes("10.0.0.0/8", 1)["subredes"][0]["red"] == "10.0.0.0/8"


@pytest.mark.parametrize("cantidad", [0, -3, 2.5, "4", True])
def test_dividir_cantidad_invalida(cantidad):
    with pytest.raises(ErrorEntrada):
        dividir_en_subredes("192.168.1.0/24", cantidad)


def test_dividir_no_caben():
    with pytest.raises(ErrorEntrada):
        dividir_en_subredes("192.168.1.0/30", 8)


# --------------------------------- vlsm ------------------------------------

def test_vlsm_ejemplo_clasico():
    r = vlsm("192.168.1.0/24", [50, 20, 10, 2])
    redes = [a["red"] for a in r["asignaciones"]]
    assert redes == ["192.168.1.0/26", "192.168.1.64/27", "192.168.1.96/28", "192.168.1.112/30"]
    assert r["direcciones_usadas"] == 64 + 32 + 16 + 4


def test_vlsm_ordena_de_mayor_a_menor_y_recuerda_el_orden():
    r = vlsm("10.0.0.0/24", [10, 100])
    assert r["asignaciones"][0]["hosts_pedidos"] == 100
    assert r["asignaciones"][0]["orden_original"] == 2


def test_vlsm_limite_exacto():
    # 62 hosts caben justos en una /26
    assert vlsm("192.168.1.0/26", [62])["asignaciones"][0]["red"] == "192.168.1.0/26"
    # 63 ya no caben
    with pytest.raises(ErrorEntrada):
        vlsm("192.168.1.0/26", [63])


def test_vlsm_sin_espacio():
    with pytest.raises(ErrorEntrada):
        vlsm("192.168.1.0/24", [200, 100])


@pytest.mark.parametrize("hosts", [[], [0], [-5], [10, "a"], "50"])
def test_vlsm_entradas_invalidas(hosts):
    with pytest.raises(ErrorEntrada):
        vlsm("192.168.1.0/24", hosts)


# ------------------------------ modo AWS (VPC) -----------------------------

def test_aws_reserva_5_direcciones():
    r = analizar_red("172.31.16.42/20", nube="aws")       # subred típica de la VPC por defecto
    assert r["direccion_red"] == "172.31.16.0"
    assert r["primer_host"] == "172.31.16.4"
    assert r["ultimo_host"] == "172.31.31.254"
    assert r["hosts_utiles"] == 4096 - 5


def test_aws_limites_de_prefijo():
    assert analizar_red("10.0.0.0/28", nube="aws")["hosts_utiles"] == 11
    assert analizar_red("172.31.0.0/16", nube="AWS")["hosts_utiles"] == 65536 - 5
    for entrada in ("10.0.0.0/29", "10.0.0.0/15"):
        with pytest.raises(ErrorEntrada):
            analizar_red(entrada, nube="aws")


def test_aws_ip_reservada_genera_aviso():
    assert analizar_red("10.0.1.2/24", nube="aws")["avisos"]       # DNS reservado por AWS
    assert not analizar_red("10.0.1.4/24", nube="aws")["avisos"]


def test_aws_dividir_vpc_por_defecto():
    r = dividir_en_subredes("172.31.0.0/16", 6, nube="aws")
    assert r["nuevo_prefijo"] == 19
    assert r["hosts_utiles_por_subred"] == 8192 - 5
    with pytest.raises(ErrorEntrada):                               # daría /29
        dividir_en_subredes("10.0.0.0/24", 32, nube="aws")


def test_aws_vlsm_usa_minimo_28():
    r = vlsm("10.0.0.0/24", [100, 3], nube="aws")
    assert [a["red"] for a in r["asignaciones"]] == ["10.0.0.0/25", "10.0.0.128/28"]
    # 123 hosts caben en /25 en red normal (126) y también en AWS (123); 124 ya no en AWS
    assert vlsm("10.0.0.0/24", [123], nube="aws")["asignaciones"][0]["red"] == "10.0.0.0/25"
    assert vlsm("10.0.0.0/24", [124], nube="aws")["asignaciones"][0]["red"] == "10.0.0.0/24"


def test_nube_desconocida():
    with pytest.raises(ErrorEntrada):
        analizar_red("10.0.0.0/24", nube="gcp")


def test_aviso_singular_cuando_sobra_una_subred():
    r = dividir_en_subredes("10.1.0.0/16", 3)
    assert any("La 1 restante queda libre." in a for a in r["avisos"])
