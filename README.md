# Agente de IA para Infraestructura de TI

## Estructura

```
herramientas/calculadora_subredes.py   Herramienta propia: subredes IPv4 (+ modo AWS VPC)
rag/ingesta.py                         Convierte corpus/ en fragmentos citables
rag/indexar.py                         Convierte los fragmentos en vectores (embeddings)
rag/buscador.py                        Devuelve las k fichas más parecidas a una pregunta
rag/evaluar_busqueda.py                Mide hit@k, MRR y separabilidad con preguntas congeladas
evaluacion/preguntas_busqueda.csv      31 preguntas de evaluación (24 con fuente, 7 sin fuente)
Dockerfile, docker-compose.yml         Contenedor del agente (no root, CPU)
corpus/                                Documentos de la biblioteca + fuentes.csv
datos/fragmentos.jsonl                 Salida de la ingesta (se regenera)
tests/                                 Pruebas automáticas
```

## Instalación

```bash
pip install -r requirements.txt
python -m pytest -v          # 66 pruebas
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

## Paso 3 – Buscador (en el servidor, con Docker)

```bash
mkdir -p datos
docker compose build
docker compose run --rm agente                                   # pruebas
docker compose run --rm agente python -m rag.ingesta             # corpus -> fichas
docker compose run --rm agente python -m rag.indexar             # fichas -> vectores
docker compose run --rm agente python -m rag.buscador "¿Qué es el teorema CAP?"
```

Modelo de embeddings: `intfloat/multilingual-e5-small` (384 dimensiones). Búsqueda exacta
por similitud coseno con NumPy: con ~150 fichas tarda menos de 1 ms, así que no se usa una
base de datos vectorial.

## Paso 4 – Evaluación del buscador

`evaluacion/preguntas_busqueda.csv` tiene 31 preguntas congeladas:

- 24 con respuesta en el corpus. Cada una lista todas sus fuentes válidas (`archivo#página`).
  Tipos: paráfrasis, dato puntual, varias fuentes válidas, trampa de título, trampa léxica y catálogo.
- 7 sin respuesta: 2 fuera de dominio, 3 temas que el corpus menciona sin explicar y 2 temas
  cercanos que no están en el corpus.

Reglas: las preguntas no copian frases de los documentos; las ya probadas a mano ("¿Qué es el
teorema CAP?", "¿Quién es Dios?") quedan fuera; el archivo no se edita para mejorar resultados.

```bash
docker compose run --rm agente python -m rag.indexar --contexto titulo  --salida datos/indice_titulo
docker compose run --rm agente python -m rag.evaluar_busqueda --indice datos/indice_titulo  --nombre titulo
docker compose run --rm agente python -m rag.indexar --contexto ninguno --salida datos/indice_ninguno
docker compose run --rm agente python -m rag.evaluar_busqueda --indice datos/indice_ninguno --nombre ninguno
```
