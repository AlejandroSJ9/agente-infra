"""
Calculadora de subredes IPv4.

Tres funciones públicas (las que usará el agente):

    analizar_red("192.168.1.10/24")
        -> datos de la red: dirección de red, broadcast, rango de hosts, etc.

    dividir_en_subredes("192.168.1.0/24", 4)
        -> divide una red en N subredes del mismo tamaño.

    vlsm("192.168.1.0/24", [50, 20, 10])
        -> asigna una subred a la medida de cada necesidad de hosts (VLSM).

Las tres aceptan nube="aws" para aplicar las reglas de subredes de una VPC de AWS
(5 direcciones reservadas por subred y prefijos entre /16 y /28), como en el
laboratorio de AWS del curso.

Todas validan sus entradas y lanzan ErrorEntrada con un mensaje en español
cuando algo no tiene sentido. Usan el módulo estándar `ipaddress`, que ya
implementa correctamente las reglas de IPv4; aquí solo se añade validación,
casos límite y una salida clara.
"""

from __future__ import annotations

import ipaddress
import math
import re

MAX_SUBREDES = 1024  # límite para no devolver respuestas gigantes al chat

# Reglas de subred por proveedor de nube
NUBES = {
    "aws": {
        "reservadas_inicio": 4,   # red, router de la VPC, DNS de AWS, uso futuro
        "reservadas_final": 1,    # última dirección (AWS no admite broadcast)
        "prefijo_min": 16,
        "prefijo_max": 28,
        "nota": "AWS reserva 5 direcciones por subred: las 4 primeras (red, router de la VPC, "
                "DNS y uso futuro) y la última.",
    },
}


class ErrorEntrada(ValueError):
    """La entrada del usuario no es válida. El mensaje se puede mostrar tal cual."""


# ---------------------------------------------------------------------------
# Lectura y validación de la entrada
# ---------------------------------------------------------------------------

def _validar_ip(texto: str) -> str:
    """Comprueba que el texto sea una IPv4 con 4 octetos entre 0 y 255."""
    partes = texto.split(".")
    if len(partes) != 4:
        raise ErrorEntrada(f"'{texto}' no es una IPv4: debe tener 4 octetos separados por puntos.")
    for p in partes:
        if not p.isdigit():
            raise ErrorEntrada(f"'{texto}' no es una IPv4: el octeto '{p}' no es un número.")
        if int(p) > 255:
            raise ErrorEntrada(f"'{texto}' no es una IPv4: el octeto {p} es mayor que 255.")
        if len(p) > 1 and p.startswith("0"):
            raise ErrorEntrada(f"'{texto}': el octeto '{p}' tiene ceros a la izquierda; escríbelo como {int(p)}.")
    return texto


def _mascara_a_prefijo(mascara: str) -> int:
    """Convierte '255.255.255.0' en 24. Rechaza máscaras no contiguas."""
    _validar_ip(mascara)
    bits = "".join(f"{int(o):08b}" for o in mascara.split("."))
    if "01" in bits:
        raise ErrorEntrada(
            f"La máscara {mascara} no es válida: sus bits en 1 deben ir seguidos "
            f"y a la izquierda (binario: {_agrupar_bits(bits)})."
        )
    return bits.count("1")


def _leer_red(entrada: str) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Network]:
    """
    Acepta:  '192.168.1.10/24'  |  '192.168.1.10 255.255.255.0'  |  '192.168.1.10/255.255.255.0'
    Devuelve la IP escrita y la red a la que pertenece.
    """
    if not isinstance(entrada, str) or not entrada.strip():
        raise ErrorEntrada("No recibí ninguna dirección. Ejemplo: 192.168.1.10/24")

    texto = entrada.strip()
    m = re.fullmatch(r"([\d.]+)\s*(?:/|\s+)\s*([\d.]+)", texto)
    if not m:
        raise ErrorEntrada(
            f"No entiendo '{texto}'. Escribe la IP con su prefijo o máscara, "
            "por ejemplo 192.168.1.10/24 o 192.168.1.10 255.255.255.0"
        )
    ip_txt, mascara_txt = m.groups()
    _validar_ip(ip_txt)

    if "." in mascara_txt:
        prefijo = _mascara_a_prefijo(mascara_txt)
    else:
        if not mascara_txt.isdigit() or not 0 <= int(mascara_txt) <= 32:
            raise ErrorEntrada(f"El prefijo /{mascara_txt} no es válido: debe estar entre /0 y /32.")
        prefijo = int(mascara_txt)

    ip = ipaddress.IPv4Address(ip_txt)
    red = ipaddress.IPv4Network(f"{ip_txt}/{prefijo}", strict=False)
    return ip, red


# ---------------------------------------------------------------------------
# Utilidades de presentación
# ---------------------------------------------------------------------------

def _agrupar_bits(bits: str) -> str:
    return ".".join(bits[i:i + 8] for i in range(0, 32, 8))


def _binario(direccion: ipaddress.IPv4Address) -> str:
    return _agrupar_bits(f"{int(direccion):032b}")


def _clase_historica(ip: ipaddress.IPv4Address) -> str:
    """Clase según el primer octeto (sistema 'classful', hoy solo de referencia)."""
    o = int(str(ip).split(".")[0])
    if o < 128:
        return "A"
    if o < 192:
        return "B"
    if o < 224:
        return "C"
    if o < 240:
        return "D (multicast)"
    return "E (experimental)"


def _tipo_direccion(ip: ipaddress.IPv4Address) -> str:
    if ip.is_loopback:
        return "loopback (127.0.0.0/8)"
    if ip.is_link_local:
        return "link-local / APIPA (169.254.0.0/16)"
    if ip.is_multicast:
        return "multicast"
    if ip in ipaddress.IPv4Network("100.64.0.0/10"):
        return "CGNAT, espacio compartido (RFC 6598)"
    if ip.is_private:
        if any(ip in ipaddress.IPv4Network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            return "privada (RFC 1918)"
        return "reservada / uso especial"
    return "pública"


def _validar_nube(nube: str | None) -> dict | None:
    if nube is None:
        return None
    if not isinstance(nube, str) or nube.strip().lower() not in NUBES:
        raise ErrorEntrada(f"Nube '{nube}' no soportada. Opciones: {', '.join(NUBES)} o ninguna.")
    return NUBES[nube.strip().lower()]


def _validar_prefijo_nube(prefijo: int, reglas: dict | None, que: str = "La subred") -> None:
    if reglas and not reglas["prefijo_min"] <= prefijo <= reglas["prefijo_max"]:
        raise ErrorEntrada(
            f"{que} /{prefijo} no es válida en la nube: los bloques deben estar entre "
            f"/{reglas['prefijo_min']} y /{reglas['prefijo_max']}."
        )


def _rango_hosts(red: ipaddress.IPv4Network, reglas: dict | None = None) -> dict:
    """Primer host, último host y cantidad, con los casos especiales /31, /32 y las reglas de nube."""
    if reglas:
        return {"primer_host": str(red.network_address + reglas["reservadas_inicio"]),
                "ultimo_host": str(red.broadcast_address - reglas["reservadas_final"]),
                "hosts_utiles": red.num_addresses - reglas["reservadas_inicio"] - reglas["reservadas_final"],
                "nota": reglas["nota"]}
    p = red.prefixlen
    if p == 32:
        return {"primer_host": str(red.network_address), "ultimo_host": str(red.network_address),
                "hosts_utiles": 1,
                "nota": "/32 identifica un único equipo (ruta de host, loopback); no hay red ni broadcast."}
    if p == 31:
        return {"primer_host": str(red.network_address), "ultimo_host": str(red.broadcast_address),
                "hosts_utiles": 2,
                "nota": "/31 en enlaces punto a punto (RFC 3021): ambas direcciones son usables."}
    return {"primer_host": str(red.network_address + 1), "ultimo_host": str(red.broadcast_address - 1),
            "hosts_utiles": red.num_addresses - 2, "nota": None}


def _resumen_red(red: ipaddress.IPv4Network, reglas: dict | None = None) -> dict:
    datos = {
        "red": str(red),
        "direccion_red": str(red.network_address),
        "broadcast": str(red.broadcast_address) if red.prefixlen < 31 else None,
        "mascara": str(red.netmask),
        "prefijo": red.prefixlen,
        "total_direcciones": red.num_addresses,
    }
    datos.update(_rango_hosts(red, reglas))
    return datos


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def analizar_red(entrada: str, nube: str | None = None) -> dict:
    """Analiza una IP con su máscara: '192.168.1.10/24' o '192.168.1.10 255.255.255.0'."""
    reglas = _validar_nube(nube)
    ip, red = _leer_red(entrada)
    _validar_prefijo_nube(red.prefixlen, reglas)
    resultado = _resumen_red(red, reglas)
    resultado.update({
        "ip_consultada": str(ip),
        "wildcard": str(red.hostmask),
        "mascara_binaria": _binario(red.netmask),
        "ip_binaria": _binario(ip),
        "clase_historica": _clase_historica(ip),
        "tipo": _tipo_direccion(ip),
        "avisos": [],
    })

    if reglas:
        if int(ip) - int(red.network_address) < reglas["reservadas_inicio"] or ip == red.broadcast_address:
            resultado["avisos"].append("La IP consultada es una de las direcciones que la nube reserva: "
                                       "no se puede asignar a una instancia.")
    elif red.prefixlen < 31:
        if ip == red.network_address:
            resultado["avisos"].append("La IP consultada es la dirección de red: no se puede asignar a un equipo.")
        elif ip == red.broadcast_address:
            resultado["avisos"].append("La IP consultada es la dirección de broadcast: no se puede asignar a un equipo.")
    if red.prefixlen == 0:
        resultado["avisos"].append("/0 representa todo el espacio IPv4 (ruta por defecto 0.0.0.0/0).")
    return resultado


def dividir_en_subredes(entrada: str, cantidad: int, nube: str | None = None) -> dict:
    """Divide una red en 'cantidad' subredes iguales (redondea a la potencia de 2 siguiente)."""
    reglas = _validar_nube(nube)
    _, red = _leer_red(entrada)
    _validar_prefijo_nube(red.prefixlen, reglas, "La red")

    if isinstance(cantidad, bool) or not isinstance(cantidad, int):
        raise ErrorEntrada("La cantidad de subredes debe ser un número entero.")
    if cantidad < 1:
        raise ErrorEntrada("La cantidad de subredes debe ser al menos 1.")
    if cantidad > MAX_SUBREDES:
        raise ErrorEntrada(f"Máximo {MAX_SUBREDES} subredes por consulta.")

    bits_prestados = math.ceil(math.log2(cantidad)) if cantidad > 1 else 0
    nuevo_prefijo = red.prefixlen + bits_prestados
    if nuevo_prefijo > 32:
        raise ErrorEntrada(
            f"No caben {cantidad} subredes en {red}: harían falta {bits_prestados} bits "
            f"y la red solo tiene {32 - red.prefixlen} bits de host."
        )

    if reglas and nuevo_prefijo > reglas["prefijo_max"]:
        raise ErrorEntrada(
            f"Dividir {red} en {cantidad} da subredes /{nuevo_prefijo}, y en la nube "
            f"la subred más pequeña permitida es /{reglas['prefijo_max']}."
        )
    subredes = list(red.subnets(new_prefix=nuevo_prefijo))
    avisos = []
    if len(subredes) != cantidad:
        avisos.append(
            f"Pediste {cantidad} subredes; con {bits_prestados} bits prestados se obtienen "
            f"{len(subredes)} (2^{bits_prestados}). "
            + ("La 1 restante queda libre." if len(subredes) - cantidad == 1
               else f"Las {len(subredes) - cantidad} restantes quedan libres.")
        )
    if nuevo_prefijo >= 31 and not reglas:
        avisos.append(f"Las subredes /{nuevo_prefijo} solo sirven para enlaces punto a punto o hosts únicos.")

    return {
        "red_original": str(red),
        "bits_prestados": bits_prestados,
        "nuevo_prefijo": nuevo_prefijo,
        "nueva_mascara": str(subredes[0].netmask),
        "subredes_obtenidas": len(subredes),
        "hosts_utiles_por_subred": _rango_hosts(subredes[0], reglas)["hosts_utiles"],
        "subredes": [_resumen_red(s, reglas) for s in subredes],
        "avisos": avisos,
    }


def vlsm(entrada: str, hosts_requeridos: list[int], nube: str | None = None) -> dict:
    """
    VLSM: asigna a cada requerimiento de hosts la subred más pequeña que lo cubre.
    Se atiende primero el requerimiento más grande (así se evita fragmentar el espacio).
    """
    reglas = _validar_nube(nube)
    _, red = _leer_red(entrada)
    _validar_prefijo_nube(red.prefixlen, reglas, "La red")

    if not isinstance(hosts_requeridos, (list, tuple)) or not hosts_requeridos:
        raise ErrorEntrada("Indica al menos una cantidad de hosts, por ejemplo [50, 20, 10].")
    if len(hosts_requeridos) > MAX_SUBREDES:
        raise ErrorEntrada(f"Máximo {MAX_SUBREDES} requerimientos por consulta.")
    for h in hosts_requeridos:
        if isinstance(h, bool) or not isinstance(h, int) or h < 1:
            raise ErrorEntrada(f"'{h}' no es válido: cada requerimiento debe ser un entero mayor o igual a 1.")

    # Orden de mayor a menor, recordando la posición original de cada pedido
    pedidos = sorted(enumerate(hosts_requeridos), key=lambda x: -x[1])

    siguiente = int(red.network_address)
    fin = int(red.broadcast_address)
    asignaciones = []

    for posicion, hosts in pedidos:
        # Subred más pequeña que cubre los hosts (+2 por red y broadcast, salvo /31 y /32)
        if reglas:
            reservadas = reglas["reservadas_inicio"] + reglas["reservadas_final"]
            prefijo = min(32 - math.ceil(math.log2(hosts + reservadas)), reglas["prefijo_max"])
        elif hosts == 1:
            prefijo = 32
        elif hosts == 2:
            prefijo = 30  # /30 es lo clásico en el aula; /31 se menciona como alternativa
        else:
            prefijo = 32 - math.ceil(math.log2(hosts + 2))

        if prefijo < red.prefixlen:
            raise ErrorEntrada(
                f"Un segmento de {hosts} hosts necesita una /{prefijo}, que es más grande que toda la red {red}."
            )
        tamano = 2 ** (32 - prefijo)
        if siguiente + tamano - 1 > fin:
            usado = siguiente - int(red.network_address)
            raise ErrorEntrada(
                f"No alcanza el espacio de {red}: tras asignar {usado} direcciones, "
                f"el segmento de {hosts} hosts necesita {tamano} más y solo quedan {fin - siguiente + 1}."
            )

        subred = ipaddress.IPv4Network((siguiente, prefijo))
        datos = _resumen_red(subred, reglas)
        datos.update({"hosts_pedidos": hosts, "orden_original": posicion + 1,
                      "desperdicio": datos["hosts_utiles"] - hosts})
        asignaciones.append(datos)
        siguiente += tamano

    usadas = siguiente - int(red.network_address)
    return {
        "red_original": str(red),
        "asignaciones": asignaciones,
        "direcciones_usadas": usadas,
        "direcciones_libres": red.num_addresses - usadas,
        "siguiente_libre": str(ipaddress.IPv4Address(siguiente)) if siguiente <= fin else None,
        "avisos": [],
    }
