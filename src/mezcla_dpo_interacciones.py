"""
Pares DPO para afinar el modelo en producción con la revisión de los logs (aura_v7 = aura_v3b + esta mezcla).

  1. data/interacciones_dpo.jsonl (src/curar_interacciones.py), con doble peso como las correcciones
     humanas de refuerzo.py.
  2. Cambios de política: ejemplos del dataset base cuya respuesta cambió respecto a la versión de git
     indicada (--antes). Elegida = respuesta nueva, rechazada = la anterior (p. ej. «antes de las 9 a.m.»
     frente a «dentro de la jornada laboral»).
  3. Repaso: una muestra de data/aura_dpo.jsonl para no olvidar lo que el modelo ya sabe.

Uso: ./hf-locql/Scripts/python.exe src/mezcla_dpo_interacciones.py --antes HEAD --repaso 150
     ./hf-locql/Scripts/python.exe src/train_dpo.py --base aura_v3b --datos data/rl/aura_v7/pares.jsonl \
         --salida aura_v7 --lr 1e-5 --epocas 2
     aura_v7b: --sin-politica --repaso 250 --salida data/rl/aura_v7b/pares.jsonl, entrenado con --lr 5e-6
"""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SFT_BASE = "dataset_aura/salida/sft/aura_sft.jsonl"


def cargar_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def par(prompt, elegida, rechazada):
    return {"prompt": prompt, "chosen": [{"role": "assistant", "content": elegida}],
            "rejected": [{"role": "assistant", "content": rechazada}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--antes", default="HEAD", help="versión de git del dataset base con la política anterior")
    ap.add_argument("--repaso", type=int, default=150)
    ap.add_argument("--sin-politica", action="store_true",
                    help="sin los pares de cambio de política: en aura_v7 hicieron que el modelo metiera la regla "
                         "de envíos en respuestas que no tenían que ver (la regla ya está en el prompt de sistema)")
    ap.add_argument("--salida", default=str(ROOT / "data" / "rl" / "aura_v7" / "pares.jsonl"))
    ap.add_argument("--semilla", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.semilla)

    interacciones = [par(e["prompt"], e["chosen"][0]["content"], e["rejected"][0]["content"])
                     for e in cargar_jsonl(ROOT / "data" / "interacciones_dpo.jsonl")]

    # El generador es determinista con la misma semilla: los ejemplos están en el mismo orden
    viejo = subprocess.run(["git", "show", f"{args.antes}:{SFT_BASE}"], cwd=ROOT, capture_output=True, check=True)
    antes = [json.loads(l) for l in viejo.stdout.decode("utf-8").splitlines() if l.strip()]
    ahora = cargar_jsonl(ROOT / SFT_BASE)
    if len(antes) != len(ahora):
        sys.exit(f"El dataset base cambió de tamaño ({len(antes)} → {len(ahora)}): no se pueden emparejar")
    politica = []
    for a, b in ([] if args.sin_politica else zip(antes, ahora)):
        ra, rb = a["messages"][-1]["content"], b["messages"][-1]["content"]
        if ra != rb:
            politica.append(par(b["messages"][:-1], rb, ra))

    repaso = rng.sample(cargar_jsonl(ROOT / "data" / "aura_dpo.jsonl"), args.repaso)
    repaso = [par(e["prompt"], e["chosen"][0]["content"], e["rejected"][0]["content"]) for e in repaso]

    filas = interacciones * 2 + politica + repaso
    rng.shuffle(filas)
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    with open(args.salida, "w", encoding="utf-8") as f:
        for x in filas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"Pares: {len(filas)} (interacciones {len(interacciones)}×2 · política {len(politica)} · repaso {len(repaso)}) → {args.salida}")


if __name__ == "__main__":
    main()
