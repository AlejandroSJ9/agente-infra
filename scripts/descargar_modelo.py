"""
Descarga un modelo GGUF de Hugging Face a la carpeta modelos/.

Uso (dentro del contenedor del agente):
    python scripts/descargar_modelo.py unsloth/Qwen3.5-2B-GGUF
    python scripts/descargar_modelo.py unsloth/Qwen3-1.7B-GGUF --cuantizacion Q4_K_M

Busca en el repositorio el archivo .gguf con la cuantización pedida (sin los archivos
"mmproj", que son para imágenes) y al final imprime la línea para el archivo .env.
"""

import argparse
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, list_repo_files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", help="por ejemplo unsloth/Qwen3.5-2B-GGUF")
    parser.add_argument("--cuantizacion", default="Q4_K_M")
    parser.add_argument("--destino", default="modelos", type=Path)
    args = parser.parse_args()

    try:
        archivos = list_repo_files(args.repo)
    except Exception as e:  # repositorio inexistente, sin red, etc.
        sys.exit(f"No pude listar {args.repo}: {e}")

    ggufs = [a for a in archivos if a.endswith(".gguf") and "mmproj" not in a.lower()]
    elegidos = sorted((a for a in ggufs if args.cuantizacion.lower() in a.lower()), key=len)
    if not elegidos:
        sys.exit(f"No hay un .gguf {args.cuantizacion} en {args.repo}. Disponibles:\n  " + "\n  ".join(ggufs))

    nombre = elegidos[0]
    print(f"Descargando {args.repo} / {nombre} ...")
    ruta = Path(hf_hub_download(args.repo, nombre, local_dir=args.destino))
    print(f"Listo: {ruta} ({ruta.stat().st_size / 1e9:.2f} GB)")
    relativa = ruta.resolve().relative_to(args.destino.resolve())   # puede venir en una subcarpeta
    print(f"\nPara usarlo, pon en .env:\nMODELO_GGUF={relativa}")


if __name__ == "__main__":
    main()
