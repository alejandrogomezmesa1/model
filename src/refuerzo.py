"""
Ciclo de refuerzo de AURA (DPO en línea con recompensas verificables + retroalimentación humana).

Pasos:
  muestrear  El modelo actual genera K respuestas por pregunta (preguntas del dataset, con su
             respuesta de referencia). La función de recompensa (src/recompensa.py) puntúa cada una.
  pares      Arma pares de preferencia: la mejor respuesta del propio modelo (o la de referencia,
             si todas fallan alguna regla) contra la peor. Suma las correcciones de la página de
             revisión (data/retroalimentacion.jsonl) con doble peso.
  evaluar    Corre los casos de evaluación (que no están en el entrenamiento) con el mismo flujo de
             la API (RAG + modelo + verificación) y reporta aprobados y recompensa promedio.
  ciclo      muestrear → pares → entrenar DPO → evaluar, y solo promueve el modelo nuevo si mejora.

Uso (desde la raíz, con la API detenida si se va a entrenar: la GPU de 4 GB no alcanza para ambos):
  ./hf-locql/Scripts/python.exe src/refuerzo.py evaluar --modelo aura_v2
  ./hf-locql/Scripts/python.exe src/refuerzo.py ciclo --modelo aura_v2 --nuevo aura_v3 --n 300
"""
import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
RL_DIR = ROOT / "data" / "rl"
RETRO_PATH = ROOT / "data" / "retroalimentacion.jsonl"
CONVERSACIONES_PATH = ROOT / "data" / "conversaciones.jsonl"
EVAL_DEFECTO = ROOT / "dataset_aura" / "salida" / "eval" / "aura_eval.jsonl"


def cargar_jsonl(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir_jsonl(ruta, filas):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        for x in filas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def cargar_modelo(nombre):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    ruta = ROOT / "models" / nombre
    tok = AutoTokenizer.from_pretrained(ruta)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    modelo = AutoModelForCausalLM.from_pretrained(ruta, dtype=torch.bfloat16).to("cuda").eval()
    return tok, modelo


def genero_de(mensajes):
    from knowledge_db import KnowledgeBase, normalize_text
    usuario = [m for m in mensajes if m["role"] == "user"]
    return KnowledgeBase.detectar_genero(normalize_text(usuario[-1]["content"]), usuario[:-1])


# ─────────────────────────────────────────────────────────────────────────────
def muestrear(args):
    import torch
    from recompensa import Recompensa
    R = Recompensa()
    tok, modelo = cargar_modelo(args.modelo)
    from api import tokens_no_latinos
    suprimidos = tokens_no_latinos(tok)  # mismo filtro de idioma que la API

    ejemplos = cargar_jsonl(ROOT / "dataset_aura" / "salida" / "sft" / "aura_sft_meta.jsonl")
    ejemplos += [{"messages": e["messages"], "meta": {"intencion": "ataque"}}
                 for e in cargar_jsonl(ROOT / "dataset_aura" / "salida" / "alineacion" / "aura_rojo.jsonl")]
    rng = random.Random(args.semilla)
    rng.shuffle(ejemplos)
    ejemplos = ejemplos[:args.n]

    salida, t0 = [], time.time()
    for i, e in enumerate(ejemplos, 1):
        prompt, referencia = e["messages"][:-1], e["messages"][-1]["content"]
        texto = tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True)
        entrada = tok(texto, return_tensors="pt").to("cuda")
        with torch.no_grad():
            out = modelo.generate(**entrada, do_sample=True, temperature=args.temperatura, top_p=0.95,
                                  max_new_tokens=args.max_tokens, num_return_sequences=args.k,
                                  pad_token_id=tok.eos_token_id, suppress_tokens=suprimidos)
        largo = entrada.input_ids.shape[1]
        respuestas = [tok.decode(o[largo:], skip_special_tokens=True).strip() for o in out]
        contexto = R.productos_del_contexto(prompt[0]["content"])
        genero = genero_de(prompt)
        puntos = [R.puntuar(r, contexto=contexto, genero=genero, pregunta=prompt[-1]["content"], referencia=referencia) for r in respuestas]
        ref = R.puntuar(referencia, contexto=contexto, genero=genero, pregunta=prompt[-1]["content"], referencia=referencia)
        salida.append({"prompt": prompt, "referencia": referencia, "puntos_referencia": ref,
                       "intencion": e.get("meta", {}).get("intencion"),
                       "muestras": [{"texto": r, **p} for r, p in zip(respuestas, puntos)]})
        if i % 10 == 0 or i == len(ejemplos):
            print(f"  {i}/{len(ejemplos)} preguntas · {(time.time() - t0) / i:.1f} s c/u", flush=True)
    escribir_jsonl(args.muestras, salida)
    tot = [m["total"] for s in salida for m in s["muestras"]]
    malas = sum(1 for s in salida for m in s["muestras"] if any(v < 0 for v in m["detalle"].values()))
    print(f"Muestras: {len(tot)} · recompensa media {sum(tot) / len(tot):.2f} · con alguna falla {malas / len(tot):.0%} → {args.muestras}")


# ─────────────────────────────────────────────────────────────────────────────
def construir_prompt_conversacion(c, kb=None):
    """Prompt de una conversación registrada. Con kb, el contexto se vuelve a buscar con la base actual:
    la corrección humana debe entrenarse con el contexto que el modelo verá hoy, no con el de ese día."""
    sistema = (ROOT / "dataset_aura" / "salida" / "sistema_aura.txt").read_text(encoding="utf-8").strip()
    contexto = kb.contexto(c["mensaje"], c.get("historial", []))[0] if kb else c.get("contexto")
    if contexto:
        sistema += "\n\n" + contexto
    return [{"role": "system", "content": sistema}] + c.get("historial", []) + [{"role": "user", "content": c["mensaje"]}]


def pares(args):
    filas = []
    tipos = {"modelo_vs_modelo": 0, "referencia_vs_modelo": 0, "humano": 0}
    for s in cargar_jsonl(args.muestras):
        ms = sorted(s["muestras"], key=lambda m: m["total"], reverse=True)
        mejor, peor = ms[0], ms[-1]
        falla = lambda m: any(v < 0 for v in m["detalle"].values())  # noqa: E731
        if falla(mejor) or s["puntos_referencia"]["total"] - mejor["total"] >= args.margen_referencia:
            # Ninguna respuesta del modelo pasó todas las reglas, o todas se alejan mucho de la referencia
            # (cambió de tema): la de referencia es la elegida
            if s["puntos_referencia"]["total"] - peor["total"] < args.margen:
                continue
            elegida, tipo = s["referencia"], "referencia_vs_modelo"
        else:
            if mejor["total"] - peor["total"] < args.margen:
                continue
            elegida, tipo = mejor["texto"], "modelo_vs_modelo"
        filas.append({"prompt": s["prompt"], "chosen": [{"role": "assistant", "content": elegida}],
                      "rejected": [{"role": "assistant", "content": peor["texto"]}]})
        tipos[tipo] += 1

    # Correcciones humanas de la página de revisión (doble peso)
    conversaciones = {c["id"]: c for c in cargar_jsonl(CONVERSACIONES_PATH)}
    from knowledge_db import KnowledgeBase
    kb = KnowledgeBase()
    for r in {v["id"]: v for v in cargar_jsonl(RETRO_PATH)}.values():  # último veredicto por conversación
        c = conversaciones.get(r["id"]) or r.get("conversacion")
        if not c or r.get("veredicto") != "mala" or not (r.get("correccion") or "").strip():
            continue
        par = {"prompt": construir_prompt_conversacion(c, kb),
               "chosen": [{"role": "assistant", "content": r["correccion"].strip()}],
               "rejected": [{"role": "assistant", "content": c.get("respuesta_cruda") or c["respuesta"]}]}
        filas += [par, par]
        tipos["humano"] += 1

    # Pares muy largos no caben en 4 GB y el entrenamiento desborda a memoria compartida (10 veces más lento)
    if args.max_tokens_par:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(ROOT / "models" / "aura_v2")
        largo = lambda m: len(tok(tok.apply_chat_template(m, tokenize=False)).input_ids)  # noqa: E731
        antes = len(filas)
        filas = [f for f in filas if max(largo(f["prompt"] + f["chosen"]), largo(f["prompt"] + f["rejected"])) <= args.max_tokens_par]
        print(f"Filtro de longitud: {antes - len(filas)} pares de más de {args.max_tokens_par} tokens descartados")

    random.Random(args.semilla).shuffle(filas)
    escribir_jsonl(args.pares, filas)
    print(f"Pares: {len(filas)} ({tipos}) → {args.pares}")


# ─────────────────────────────────────────────────────────────────────────────
def preguntas_de_entrenamiento():
    """Todas las preguntas que algún modelo vio al entrenar: dataset actual, dataset con el que se
    entrenaron aura_v2/v3/v3b (commit bd31702) y los prompts de las rondas de refuerzo."""
    from recompensa import clave
    vistas = set()

    def agregar_conversaciones(filas):
        for e in filas:
            for m in e.get("messages") or e.get("prompt") or []:
                if m["role"] == "user":
                    vistas.add(clave(m["content"]))
            if e.get("meta", {}).get("pregunta_limpia"):
                vistas.add(clave(e["meta"]["pregunta_limpia"]))

    salida = ROOT / "dataset_aura" / "salida"
    agregar_conversaciones(cargar_jsonl(salida / "sft" / "aura_sft_meta.jsonl"))
    agregar_conversaciones(cargar_jsonl(salida / "alineacion" / "aura_rojo.jsonl"))
    for ruta in ("sft/aura_sft_meta.jsonl", "alineacion/aura_rojo.jsonl"):
        r = subprocess.run(["git", "show", f"bd31702:dataset_aura/salida/{ruta}"], cwd=ROOT, capture_output=True)
        if r.returncode == 0:
            agregar_conversaciones([json.loads(l) for l in r.stdout.decode("utf-8").splitlines() if l.strip()])
    for muestras in RL_DIR.glob("*/muestras.jsonl"):
        agregar_conversaciones(cargar_jsonl(muestras))
    return vistas


def crear_eval(args):
    """Evaluación grande y limpia: casos generados con otras semillas, sin ninguna pregunta de entrenamiento."""
    sys.path.insert(0, str(ROOT / "dataset_aura"))
    import generar_dataset as G
    from recompensa import clave
    vistas = preguntas_de_entrenamiento()
    datos = G.descargar(G.API_DEF, str(ROOT / "data" / "cache_tienda"))
    casos, descartados = [], 0
    for semilla in [int(s) for s in args.semillas.split(",")]:
        for c in G.construir_eval(G.Generador(datos, semilla), n_por_intencion=args.n_por_intencion):
            k = clave(c["mensaje"])
            if k in vistas:
                descartados += 1
                continue
            vistas.add(k)
            casos.append(c)
    for i, c in enumerate(casos, 1):
        c["id"] = f"evalg-{i:04d}"
    escribir_jsonl(args.casos, casos)
    print(f"Evaluación limpia: {len(casos)} casos ({descartados} descartados por estar en algún entrenamiento) → {args.casos}")


# ─────────────────────────────────────────────────────────────────────────────
def evaluar(args):
    """Casos de evaluación con el flujo real de la API (KnowledgeBase.contexto + modelo + verificar_productos)."""
    import api
    from knowledge_db import KnowledgeBase
    from recompensa import Recompensa, clave
    R = Recompensa()
    kb = KnowledgeBase()
    tok, modelo = cargar_modelo(args.modelo)
    api.STATE.update(kb=kb, catalogo=kb.catalogo_precios(), kits=kb.nombres_kits(), urls=kb.urls_productos(), device="cuda",
                     model=modelo, tokenizer=tok, model_display=args.modelo)
    os.environ["AURA_REGISTRO"] = "0"

    casos = cargar_jsonl(args.casos)
    resultados, por_grupo, recompensas = [], {}, []
    for c in casos:
        traza = {}
        resp, _, _ = api.run_turn(c["mensaje"], [], None, {"temperature": 0, "max_tokens": 350}, traza)
        fallas = [f"falta: {p}" for p in c["debe_incluir"] if not re.search(p, resp, re.M)]
        fallas += [f"prohibido: {p}" for p in c["no_debe_incluir"] if re.search(p, resp)]
        fallas += [f"producto inexistente: {m.group(1)}" for m in re.finditer(r'^\s*[-*•]\s*\*\*(.+?)\*\*', resp, re.M)
                   if clave(m.group(1)) not in R.productos]
        contexto = R.productos_del_contexto(traza.get("contexto", ""))
        p = R.puntuar(traza.get("respuesta_cruda", resp), contexto=contexto,
                      genero=genero_de([{"role": "user", "content": c["mensaje"]}]), pregunta=c["mensaje"])
        recompensas.append(p["total"])
        ok = not fallas
        g = por_grupo.setdefault(c["grupo"], [0, 0])
        g[0] += ok
        g[1] += 1
        resultados.append({"id": c["id"], "intencion": c["intencion"], "mensaje": c["mensaje"], "respuesta": resp,
                           "aprobado": ok, "fallas": fallas, "recompensa": p})
    aprobados = sum(r["aprobado"] for r in resultados)
    violaciones = sum(any(f.startswith(("prohibido", "producto")) for f in r["fallas"]) for r in resultados)
    reporte = {"modelo": args.modelo, "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
               "aprobados": aprobados, "total": len(casos), "violaciones": violaciones,
               "recompensa_media": round(sum(recompensas) / len(recompensas), 3),
               "por_grupo": por_grupo, "casos": resultados}
    RL_DIR.mkdir(parents=True, exist_ok=True)
    defecto = Path(args.casos).resolve() == EVAL_DEFECTO.resolve()
    ruta = RL_DIR / (f"eval_{args.modelo}.json" if defecto else f"eval_{args.modelo}_{Path(args.casos).stem}.json")
    ruta.write_text(json.dumps(reporte, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.modelo}: aprobados {aprobados}/{len(casos)} ({aprobados / len(casos):.1%}) · violaciones {violaciones} · "
          f"recompensa media {reporte['recompensa_media']}")
    for g, (a, n) in sorted(por_grupo.items()):
        print(f"  {g:<18} {a}/{n}")
    print(f"Reporte: {ruta}")
    return reporte


# ─────────────────────────────────────────────────────────────────────────────
def correr(paso, **kw):
    """Cada paso en su propio proceso: así la GPU queda libre entre muestrear, entrenar y evaluar."""
    cmd = [sys.executable, str(Path(__file__)), paso] + [x for k, v in kw.items() for x in (f"--{k}", str(v))]
    print(f"\n=== {paso} ===", flush=True)
    subprocess.run(cmd, check=True)


def ciclo(args):
    ronda = RL_DIR / args.nuevo
    muestras, pares_path = ronda / "muestras.jsonl", ronda / "pares.jsonl"
    if not (RL_DIR / f"eval_{args.modelo}.json").exists():
        correr("evaluar", modelo=args.modelo)
    correr("muestrear", modelo=args.modelo, n=args.n, k=args.k, semilla=args.semilla, muestras=muestras)
    correr("pares", muestras=muestras, pares=pares_path, semilla=args.semilla)
    print("\n=== entrenar ===", flush=True)
    subprocess.run([sys.executable, str(ROOT / "src" / "train_dpo.py"), "--base", args.modelo,
                    "--datos", str(pares_path), "--salida", args.nuevo], check=True)
    correr("evaluar", modelo=args.nuevo)
    antes = json.loads((RL_DIR / f"eval_{args.modelo}.json").read_text(encoding="utf-8"))
    despues = json.loads((RL_DIR / f"eval_{args.nuevo}.json").read_text(encoding="utf-8"))
    mejora = (despues["violaciones"] <= antes["violaciones"] and
              (despues["aprobados"], despues["recompensa_media"]) > (antes["aprobados"], antes["recompensa_media"]))
    print(f"\n{args.modelo}: {antes['aprobados']}/{antes['total']}, violaciones {antes['violaciones']}, recompensa {antes['recompensa_media']}")
    print(f"{args.nuevo}: {despues['aprobados']}/{despues['total']}, violaciones {despues['violaciones']}, recompensa {despues['recompensa_media']}")
    print("✔ Mejora: usa el modelo nuevo con AURA_MODELO=" + args.nuevo if mejora
          else "✘ No mejora: se mantiene " + args.modelo)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="paso", required=True)
    m = sub.add_parser("muestrear")
    m.add_argument("--modelo", default="aura_v2")
    m.add_argument("--n", type=int, default=300)
    m.add_argument("--k", type=int, default=4)
    m.add_argument("--temperatura", type=float, default=0.8)
    m.add_argument("--max_tokens", type=int, default=300)
    m.add_argument("--semilla", type=int, default=1)
    m.add_argument("--muestras", default=str(RL_DIR / "muestras.jsonl"))
    p = sub.add_parser("pares")
    p.add_argument("--muestras", default=str(RL_DIR / "muestras.jsonl"))
    p.add_argument("--pares", default=str(RL_DIR / "pares.jsonl"))
    p.add_argument("--margen", type=float, default=1.0)
    p.add_argument("--max_tokens_par", type=int, default=1500, help="0 = sin filtro de longitud")
    p.add_argument("--margen_referencia", type=float, default=1.8,
                   help="si la referencia supera a la mejor muestra por esto (parecido 0,6 de 3), se elige la referencia")
    p.add_argument("--semilla", type=int, default=1)
    e = sub.add_parser("evaluar")
    e.add_argument("--modelo", default="aura_v2")
    e.add_argument("--casos", default=str(EVAL_DEFECTO), help="archivo de casos (por defecto, la evaluación del dataset)")
    ce = sub.add_parser("crear_eval")
    ce.add_argument("--semillas", default="101,102,103")
    ce.add_argument("--n_por_intencion", type=int, default=2)
    ce.add_argument("--casos", default=str(RL_DIR / "eval_limpia.jsonl"))
    c = sub.add_parser("ciclo")
    c.add_argument("--modelo", default="aura_v2")
    c.add_argument("--nuevo", required=True)
    c.add_argument("--n", type=int, default=300)
    c.add_argument("--k", type=int, default=4)
    c.add_argument("--semilla", type=int, default=1)
    args = ap.parse_args()
    {"muestrear": muestrear, "pares": pares, "evaluar": evaluar, "crear_eval": crear_eval, "ciclo": ciclo}[args.paso](args)


if __name__ == "__main__":
    main()
