"""
Convierte el dataset de AURA (dataset_aura/salida) al formato de entrenamiento de TRL.

- SFT: aura_sft.jsonl + aura_rojo.jsonl → data/aura_sft.jsonl en formato conversacional
  prompt/completion: la pérdida se calcula solo sobre la última respuesta de AURA, no sobre
  el prompt de sistema (que ocupa ~735 tokens y es igual en todos los ejemplos).
- DPO: aura_dpo.jsonl → data/aura_dpo.jsonl (prompt conversacional + chosen/rejected).

Comprueba que cada ejemplo empiece con el mismo prompt de sistema que usa la API
(dataset_aura/salida/sistema_aura.txt), para entrenar con el formato real de inferencia.

Uso:  ./hf-locql/Scripts/python.exe src/preparar_datos_aura.py
"""
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SALIDA = ROOT / "dataset_aura" / "salida"
DATA = ROOT / "data"


def cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir(ruta, filas):
    with open(ruta, "w", encoding="utf-8") as f:
        for x in filas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def main():
    sistema = (SALIDA / "sistema_aura.txt").read_text(encoding="utf-8").strip()

    def revisar_sistema(msgs, origen):
        if msgs[0]["role"] != "system" or not msgs[0]["content"].startswith(sistema):
            raise SystemExit(f"{origen}: el prompt de sistema no coincide con sistema_aura.txt; regenera el dataset")

    sft = []
    for origen in ("sft/aura_sft.jsonl", "alineacion/aura_rojo.jsonl"):
        for i, e in enumerate(cargar(SALIDA / origen)):
            msgs = e["messages"]
            revisar_sistema(msgs, f"{origen}:{i}")
            assert msgs[-1]["role"] == "assistant"
            sft.append({"prompt": msgs[:-1], "completion": [msgs[-1]]})

    dpo = []
    for i, p in enumerate(cargar(SALIDA / "alineacion" / "aura_dpo.jsonl")):
        revisar_sistema(p["prompt"], f"dpo:{i}")
        dpo.append({"prompt": p["prompt"], "chosen": p["chosen"], "rejected": p["rejected"]})

    escribir(DATA / "aura_sft.jsonl", sft)
    escribir(DATA / "aura_dpo.jsonl", dpo)
    print(f"SFT: {len(sft)} ejemplos → {DATA / 'aura_sft.jsonl'}")
    print(f"DPO: {len(dpo)} pares → {DATA / 'aura_dpo.jsonl'}")


if __name__ == "__main__":
    main()
