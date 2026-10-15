"""
Dataset curado a partir de los logs del chatbot.

Une los dos registros (data/conversaciones.jsonl de la API y data/interacciones_chat.jsonl del chat
antiguo) con la revisión turno a turno de data/revision_interacciones.json (puntaje, problemas y la
respuesta ideal) y escribe:

  data/interacciones_sft.jsonl   {"prompt": [...], "completion": [...]}         (formato de aura_sft.jsonl)
  data/interacciones_dpo.jsonl   {"prompt": [...], "chosen": [...], "rejected": [...]}  (formato de aura_dpo.jsonl)
  data/interacciones_reporte.md  evaluación de cada turno y resumen de problemas

El prompt es el mismo de la API: sistema_aura.txt + contexto del RAG actual + historial registrado.
Cuando la revisión fija productos («contexto»), el CATÁLOGO RELEVANTE se arma con esas filas.
Cada respuesta elegida pasa por src/recompensa.py: si alguna regla la penaliza, el script se detiene.

Pares DPO: solo turnos con puntaje ≤ 3 que la revisión humana no marcó como buenos.

Uso: ./hf-locql/Scripts/python.exe src/curar_interacciones.py
"""
import collections
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
DATA = ROOT / "data"
SISTEMA = (ROOT / "dataset_aura" / "salida" / "sistema_aura.txt").read_text(encoding="utf-8").strip()
CONOCIMIENTO = ROOT / "dataset_aura" / "salida" / "rag" / "conocimiento.json"
COMANDOS_TERMINAL = {"salir", "corregir"}
TURNOS_HISTORIAL = 2  # la API manda los últimos 2 intercambios
MAX_TOKENS = 2048  # max_length de train_sft.py y train_dpo.py


def cargar_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir_jsonl(ruta, filas):
    with open(ruta, "w", encoding="utf-8") as f:
        for x in filas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def turnos_registrados():
    """{id: turno} con mensaje, historial y respuesta de los dos registros."""
    turnos = {}
    retro = {}
    for r in cargar_jsonl(DATA / "retroalimentacion.jsonl"):
        retro[r["id"]] = r  # el último veredicto manda, como en refuerzo.py
    for c in cargar_jsonl(DATA / "conversaciones.jsonl"):
        turnos[c["id"]] = {"fuente": "api", "fecha": c["fecha"], "modelo": c.get("modelo"),
                           "mensaje": c["mensaje"], "historial": c.get("historial", []),
                           "respuesta": c.get("respuesta_cruda") or c["respuesta"],
                           "humano": retro.get(c["id"], {}).get("veredicto")}
    # El chat antiguo no guardaba historial: se arma con los turnos previos de la misma sesión
    previos = collections.defaultdict(list)
    for i, c in enumerate(cargar_jsonl(DATA / "interacciones_chat.jsonl")):
        hist = [m for u, a in previos[c["session_id"]][-TURNOS_HISTORIAL:]
                for m in ({"role": "user", "content": u}, {"role": "assistant", "content": a})]
        turnos[f"ic-{i}"] = {"fuente": "chat_antiguo", "fecha": c["timestamp"][:19], "modelo": "mi_modelo_perfumista_v1",
                             "mensaje": c["user"], "historial": hist, "respuesta": c["assistant"], "humano": None}
        if c["user"].strip().lower() not in COMANDOS_TERMINAL:
            previos[c["session_id"]].append((c["user"], c["assistant"]))
    return turnos


def main():
    from knowledge_db import KnowledgeBase, normalize_text
    from recompensa import Recompensa, clave

    from transformers import AutoTokenizer

    kb = KnowledgeBase()
    R = Recompensa()
    tok = AutoTokenizer.from_pretrained(ROOT / "models" / "aura_v2")
    largo = lambda m: len(tok(tok.apply_chat_template(m, tokenize=False)).input_ids)  # noqa: E731
    productos = {p["name"]: p for p in json.loads(CONOCIMIENTO.read_text(encoding="utf-8"))["productos"]}
    revision = json.loads((DATA / "revision_interacciones.json").read_text(encoding="utf-8"))["turnos"]
    turnos = turnos_registrados()

    sin_revisar = set(turnos) - {r["id"] for r in revision}
    desconocidos = {r["id"] for r in revision} - set(turnos)
    if sin_revisar or desconocidos:
        sys.exit(f"Revisión incompleta. Sin revisar: {sorted(sin_revisar)} · ids que no están en los logs: {sorted(desconocidos)}")
    por_id = {r["id"]: r for r in revision}

    sft, dpo, errores, filas_reporte = [], [], [], []
    for r in revision:
        t = turnos[r["id"]]
        mensaje = r.get("mensaje") or t["mensaje"]
        incluir = r.get("incluir", True)
        mejor = por_id.get(r.get("mejor"))
        elegida = r.get("ideal") or (mejor and (mejor.get("ideal") or turnos[mejor["id"]]["respuesta"])) \
            or (t["respuesta"] if r["puntaje"] >= 4 else None)
        filas_reporte.append((r, t, mensaje, elegida))
        if not incluir:
            continue
        if not elegida:
            errores.append(f"{r['id']}: incluido sin respuesta elegida")
            continue

        if r.get("contexto"):
            faltan = [n for n in r["contexto"] if n not in productos]
            if faltan:
                errores.append(f"{r['id']}: productos de contexto que no existen: {faltan}")
                continue
            contexto = "CATÁLOGO RELEVANTE:\n" + "\n".join(productos[n]["contexto"] for n in r["contexto"])
        else:
            contexto = kb.contexto(mensaje, t["historial"])[0]
        sistema = SISTEMA + ("\n\n" + contexto if contexto else "")
        historial = list(t["historial"])
        prompt = [{"role": "system", "content": sistema}] + historial + [{"role": "user", "content": mensaje}]
        # El entrenamiento corta en MAX_TOKENS: se quita el intercambio más antiguo hasta que quepa
        respuestas = [elegida, t["respuesta"]]
        while historial and max(largo(prompt + [{"role": "assistant", "content": x}]) for x in respuestas) > MAX_TOKENS:
            historial = historial[2:]
            prompt = [{"role": "system", "content": sistema}] + historial + [{"role": "user", "content": mensaje}]

        # La respuesta elegida no puede romper ninguna regla de la recompensa
        usuario = [m for m in prompt if m["role"] == "user"]
        # «genero» en la revisión corrige al detector cuando el cliente describe un producto («esa es de dama»)
        genero = r.get("genero") or KnowledgeBase.detectar_genero(normalize_text(mensaje), usuario[:-1])
        en_contexto = Recompensa.productos_del_contexto(sistema)
        puntos = R.puntuar(elegida, contexto=en_contexto, genero=genero, pregunta=mensaje)
        fallas = {k: v for k, v in puntos["detalle"].items() if v < 0}
        # «pregunta_genero_ya_dicho» se ignora cuando el género detectado viene solo del historial antiguo
        # y la respuesta pregunta a propósito (unisex primero y luego el género)
        if fallas.get("pregunta_genero_ya_dicho") and not KnowledgeBase.detectar_genero(normalize_text(mensaje)):
            fallas.pop("pregunta_genero_ya_dicho")
        if fallas:
            errores.append(f"{r['id']}: la respuesta elegida falla {fallas}")
        # Tamaños: si dice «N ml» junto a un producto, debe existir ese tamaño
        for nombre, ml in re.findall(r'\*\*(.+?)\*\*[^\n]*?(\d+)\s?ml', elegida):
            p = R.productos.get(clave(nombre))
            if p and f"{ml}ml" not in [s.replace(" ", "") for s in p.get("sizes", [])]:
                errores.append(f"{r['id']}: {nombre} no viene en {ml} ml")
        if re.search(r'https?://', elegida):
            for url in re.findall(r'https?://\S+?(?=[\s)]|$)', elegida):
                if url.rstrip('.,') not in {"https://alta-densidad-page.vercel.app/top10"}:
                    errores.append(f"{r['id']}: URL no verificada {url}")

        meta = {"id": r["id"], "fuente": t["fuente"], "puntaje_original": r["puntaje"], "problemas": r["problemas"]}
        sft.append({"prompt": prompt, "completion": [{"role": "assistant", "content": elegida}], "meta": meta})
        if r["puntaje"] <= 3 and t["humano"] != "buena" and t["respuesta"].strip() != elegida.strip():
            dpo.append({"prompt": prompt, "chosen": [{"role": "assistant", "content": elegida}],
                        "rejected": [{"role": "assistant", "content": t["respuesta"]}], "meta": meta})

    if errores:
        print("ERRORES:\n  " + "\n  ".join(errores))
        sys.exit(1)

    # Un mismo prompt (envío a Medellín) aparece varias veces en SFT: se deja una sola completion
    vistos, sft_unico = set(), []
    for e in sft:
        k = (clave(e["prompt"][-1]["content"]), e["completion"][0]["content"])
        if k not in vistos:
            vistos.add(k)
            sft_unico.append(e)

    escribir_jsonl(DATA / "interacciones_sft.jsonl", sft_unico)
    escribir_jsonl(DATA / "interacciones_dpo.jsonl", dpo)
    escribir_reporte(filas_reporte, len(sft_unico), len(dpo))
    print(f"Turnos revisados: {len(revision)} · SFT: {len(sft_unico)} · DPO: {len(dpo)}")


def escribir_reporte(filas, n_sft, n_dpo):
    problemas = collections.Counter(p for r, *_ in filas for p in r["problemas"])
    puntajes = collections.Counter(r["puntaje"] for r, *_ in filas)
    por_fuente = collections.defaultdict(list)
    for r, t, *_ in filas:
        por_fuente[t["fuente"]].append(r["puntaje"])
    corto = lambda s, n=110: (s or "").replace("\n", " ").replace("|", "/")[:n] + ("…" if len(s or "") > n else "")  # noqa: E731

    lineas = ["# Revisión de las interacciones del chatbot", "",
              f"Turnos revisados: {len(filas)} · ejemplos SFT: {n_sft} · pares DPO: {n_dpo}", "",
              "## Puntaje promedio por origen", "", "| Origen | Turnos | Promedio (1-5) |", "|---|---|---|"]
    for fuente, ps in por_fuente.items():
        lineas.append(f"| {fuente} | {len(ps)} | {sum(ps) / len(ps):.1f} |")
    lineas += ["", "## Distribución de puntajes", "", "| Puntaje | Turnos |", "|---|---|"]
    lineas += [f"| {k} | {puntajes[k]} |" for k in sorted(puntajes)]
    lineas += ["", "## Problemas más frecuentes", "", "| Problema | Turnos |", "|---|---|"]
    lineas += [f"| {k} | {v} |" for k, v in problemas.most_common()]
    lineas += ["", "## Turno por turno", "", "| Id | Origen | Mensaje | Puntaje | Problemas | Usado | Comentario |",
               "|---|---|---|---|---|---|---|"]
    for r, t, mensaje, elegida in filas:
        usado = "sí" if r.get("incluir", True) else "no"
        lineas.append(f"| {r['id']} | {t['fuente']} | {corto(mensaje, 60)} | {r['puntaje']} | "
                      f"{', '.join(r['problemas']) or '—'} | {usado} | {corto(r.get('comentario', ''), 160)} |")
    (DATA / "interacciones_reporte.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
