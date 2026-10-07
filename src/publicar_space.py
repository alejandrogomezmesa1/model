"""
Publica la API de AURA en un Space de Hugging Face (Docker, CPU).

Sube solo lo que necesita api.py en producción: el código de la API, la base de conocimiento,
el prompt y el catálogo, más los archivos de space/ (Dockerfile, requirements, README).
El modelo no se sube aquí: el Space lo descarga de AURA_MODELO_HF (ver space/Dockerfile).

Uso:  ./hf-locql/Scripts/python.exe src/publicar_space.py [usuario/nombre-space]
"""
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ARCHIVOS = {
    # ruta en el Space: ruta local
    "Dockerfile": "space/Dockerfile",
    "requirements.txt": "space/requirements.txt",
    "README.md": "space/README.md",
    "api.py": "api.py",
    "src/knowledge_db.py": "src/knowledge_db.py",
    "src/post_validator.py": "src/post_validator.py",
    "data/allowed_origins.json": "data/allowed_origins.json",
    "dataset_aura/salida/sistema_aura.txt": "dataset_aura/salida/sistema_aura.txt",
    "dataset_aura/salida/rag/conocimiento.json": "dataset_aura/salida/rag/conocimiento.json",
}


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "mansamusa04/aura-api"
    api = HfApi()
    api.create_repo(repo, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    ops = [CommitOperationAdd(path_in_repo=destino, path_or_fileobj=str(ROOT / origen))
           for destino, origen in ARCHIVOS.items()]
    commit = api.create_commit(repo, repo_type="space", operations=ops, commit_message="Publicar API de AURA")
    print(f"Space actualizado: https://huggingface.co/spaces/{repo}")
    print(f"Commit: {commit.commit_url}")


if __name__ == "__main__":
    main()
