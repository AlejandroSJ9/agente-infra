# Agente de IA para Infraestructura de TI

## Estructura

```
herramientas/calculadora_subredes.py   Herramienta propia: subredes IPv4 (+ modo AWS VPC)
rag/ingesta.py                         Convierte corpus/ en fragmentos citables
corpus/                                Documentos de la biblioteca + fuentes.csv
datos/fragmentos.jsonl                 Salida de la ingesta (se regenera)
tests/                                 Pruebas automáticas
```

## Instalación

```bash
pip install -r requirements.txt
python -m pytest -v          # 47 pruebas
```

## Paso 1 – Calculadora de subredes IPv4

- `analizar_red("192.168.1.10/24")`: red, broadcast, rango de hosts, máscara, wildcard, binario, tipo de IP.
- `dividir_en_subredes("192.168.1.0/24", 4)`: N subredes iguales.
- `vlsm("192.168.1.0/24", [50, 20, 10])`: una subred a la medida de cada segmento.
- Las tres aceptan `nube="aws"`: AWS reserva 5 direcciones por subred (las 4 primeras y la última)
  y solo admite bloques entre /16 y /28. Ejemplo: `analizar_red("172.31.16.42/20", nube="aws")`.

## Paso 2 – Corpus e ingesta

1. Copia el documento en `corpus/` (PDF, Markdown o el catálogo .xlsx).
2. Regístralo en `corpus/fuentes.csv` (título, autor, año, tipo, origen). Un archivo sin registro se omite.
3. Ejecuta `python -m rag.ingesta`, que genera `datos/fragmentos.jsonl`.

Cada fragmento guarda `cita` (documento, autor, año, página y sección), que el bot mostrará como fuente.
Las imágenes (infografías) se transcriben a Markdown, porque el bot solo busca en texto.
