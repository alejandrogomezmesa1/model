"""
Script de Aprendizaje Activo:
Procesa el historial de interacciones reales del chat y las correcciones del usuario
para actualizar automáticamente los datasets de entrenamiento (SFT y DPO).
"""

import os
import sys
import json
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def procesar_interacciones():
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"

    interacciones_path = data_dir / "interacciones_chat.jsonl"
    correcciones_path = data_dir / "correcciones_activas.jsonl"
    reasoning_path = data_dir / "dataset_reasoning.json"
    dpo_path = data_dir / "dataset_dpo.json"

    system_prompt = (
        "Eres un maestro perfumista y asesor experto de Alta Densidad. "
        "Posees un conocimiento enciclopédico de perfumes comerciales, química de fijadores y formulación en laboratorio. "
        "Respondes siempre en español con precisión técnica, claridad, amabilidad y rigor profesional."
    )

    # 1. Cargar dataset actual de SFT
    dataset_sft = []
    if reasoning_path.exists():
        with open(reasoning_path, "r", encoding="utf-8") as f:
            dataset_sft = json.load(f)

    # 2. Cargar dataset actual de DPO
    dataset_dpo = []
    if dpo_path.exists():
        with open(dpo_path, "r", encoding="utf-8") as f:
            dataset_dpo = json.load(f)

    prompts_existentes_sft = set()
    for item in dataset_sft:
        msgs = item.get("messages", [])
        u = next((m["content"].strip().lower() for m in msgs if m["role"] == "user"), "")
        if u:
            prompts_existentes_sft.add(u)

    nuevos_sft = 0
    nuevos_dpo = 0

    # 3. Procesar correcciones activas del usuario (Oro para DPO y SFT)
    if correcciones_path.exists():
        with open(correcciones_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    c = json.loads(line)
                    prompt = c.get("prompt", "").strip()
                    chosen = c.get("chosen", "").strip()
                    rejected = c.get("rejected", "").strip()

                    if prompt and chosen:
                        # Agregar a SFT como ejemplo perfecto
                        if prompt.lower() not in prompts_existentes_sft:
                            dataset_sft.append({
                                "messages": [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": chosen}
                                ]
                            })
                            prompts_existentes_sft.add(prompt.lower())
                            nuevos_sft += 1

                        # Agregar a DPO (Chosen vs Rejected)
                        if rejected and chosen != rejected:
                            dataset_dpo.append({
                                "prompt": prompt,
                                "chosen": chosen,
                                "rejected": rejected
                            })
                            nuevos_dpo += 1
                except Exception:
                    pass

    # Guardar datasets actualizados
    with open(reasoning_path, "w", encoding="utf-8") as f:
        json.dump(dataset_sft, f, ensure_ascii=False, indent=2)

    with open(dpo_path, "w", encoding="utf-8") as f:
        json.dump(dataset_dpo, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("      SISTEMA DE APRENDIZAJE ACTIVO Y REALIMENTACIÓN      ")
    print("=" * 60)
    print(f"Nuevos diálogos incorporados a SFT (Razonamiento): {nuevos_sft}")
    print(f"Total diálogos en dataset SFT: {len(dataset_sft)}")
    print(f"Nuevos pares de preferencia incorporados a DPO: {nuevos_dpo}")
    print(f"Total pares en dataset DPO: {len(dataset_dpo)}")
    print("\nDatasets listos para reentrenar cuando desees con:")
    print("  & ./hf-locql/Scripts/python.exe src/train_sft.py")
    print("  & ./hf-locql/Scripts/python.exe src/train_dpo.py")
    print("=" * 60)

if __name__ == "__main__":
    procesar_interacciones()
