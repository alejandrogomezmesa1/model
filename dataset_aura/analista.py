"""
AURA analista de mercado: redacta el informe diario de la vigía de tendencias de la tienda.

La investigación la hacen herramientas programadas en el servidor de la tienda
(AltaDensidadPAGE/backend/services/vigia.js): autocompletado de Google Colombia, Google Noticias y
comunidades de perfumería. Ellas entregan SEÑALES ya cruzadas con el catálogo; el modelo solo las
convierte en un informe corto y accionable para el equipo (es interno: puede nombrar los originales).

Este módulo tiene todo lo de la tarea, para que el entrenamiento y la API usen exactamente lo mismo:
  - SISTEMA_ANALISTA y contexto(senales): el prompt de sistema y el mensaje de usuario.
  - informe_ideal(senales, rnd): la respuesta de referencia (redacción variada, siempre fiel a las señales).
  - verificar(texto, senales, catalogo): rechaza informes que inventan perfumes o mandan a publicar agotados.
  - generar(...): ejemplos SFT y pares DPO sintéticos a partir del catálogo real (salida/rag/conocimiento.json).

Uso:  python dataset_aura/analista.py [--n 400] [--dpo 160] [--semilla 2026]
      → salida/analista/analista_sft.jsonl y salida/analista/analista_dpo.jsonl
Luego src/preparar_datos_aura.py los suma al entrenamiento.
"""
import argparse
import json
import os
import random
import re
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))

SISTEMA_ANALISTA = (
    "Eres AURA en modo analista de mercado de Fragancias de Alta Densidad (Medellín, Colombia). "
    "Recibes SEÑALES del mercado ya investigadas por herramientas (búsquedas en Google Colombia, noticias y "
    "comunidades) y cruzadas con el catálogo. Escribes un informe interno para el equipo, en español, breve y "
    "accionable.\n\n"
    "REGLAS\n"
    "1. Usa solo los perfumes, notas, marcas y búsquedas que aparecen en las SEÑALES. No inventes ninguno.\n"
    "2. Nunca recomiendes publicar ni destacar un perfume marcado como no vendible.\n"
    "3. Los perfumes con demanda y sin existencias van en la línea de reponer.\n"
    "4. Formato: líneas cortas que empiezan con 📈 (lo que más suena), 🔺 (lo que sube, si hay), "
    "🌿 (notas en alza), 📦 (reponer, si hay), 🛒 (lo que buscan y no tenemos, si hay) y ✅ (acción de hoy: "
    "qué publicar en Marketplace y qué destacar en la web). Máximo 7 líneas.\n"
    "5. Sin saludos ni despedidas. Sin cifras que no estén en las SEÑALES."
)


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


def contexto(senales):
    """Mensaje de usuario con las señales (mismo formato en entrenamiento y en la API)."""
    lineas = ["SEÑALES DEL MERCADO", "PERFUMES DEL CATÁLOGO CON SEÑAL (puntaje 0-100):"]
    for p in senales.get("perfumes", [])[:12]:
        estado = []
        if p.get("vendible") is False:
            estado.append("NO VENDIBLE")
        elif p.get("agotado"):
            estado.append("sin existencias (se vende por encargo)")
        cambio = p.get("cambio")
        if isinstance(cambio, (int, float)) and cambio:
            estado.append(f"{'+' if cambio > 0 else ''}{int(cambio)} vs. informe anterior")
        motivo = (p.get("motivos") or [""])[0]
        lineas.append(f"- {p.get('original')} ({p.get('marca') or 's/marca'}) | {p.get('puntaje', 0)}"
                      + (f" | {'; '.join(estado)}" if estado else "") + (f" | {motivo}" if motivo else ""))
    for clave, titulo in (("notas", "NOTAS EN ALZA"), ("agotados_con_demanda", "CON DEMANDA Y SIN EXISTENCIAS"),
                          ("sin_catalogo", "BUSCAN Y NO TENEMOS"), ("noticias", "TITULARES")):
        valores = [str(v) for v in senales.get(clave, []) if v]
        lineas.append(f"{titulo}: " + (" | ".join(valores) if valores else "(ninguno)"))
    return "\n".join(lineas)


def _lista(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]


def informe_ideal(senales, rnd=None):
    """Informe de referencia: fiel a las señales, con redacción variada."""
    rnd = rnd or random.Random(0)
    perfumes = senales.get("perfumes", [])
    vendibles = [p for p in perfumes if p.get("vendible") is not False]
    out = []
    if perfumes:
        top = [p["original"] for p in perfumes[:4]]
        out.append(rnd.choice(["📈 Lo que más suena hoy: {}.", "📈 Lo más buscado de tu catálogo: {}.",
                               "📈 Encabezan las señales: {}."]).format(_lista(top)))
    suben = [p for p in perfumes if isinstance(p.get("cambio"), (int, float)) and p["cambio"] >= 10][:3]
    if suben:
        out.append(rnd.choice(["🔺 Subiendo: {}.", "🔺 Ganan fuerza: {}."]).format(
            _lista(f"{p['original']} (+{int(p['cambio'])})" for p in suben)))
    notas = senales.get("notas", [])[:5]
    if notas:
        out.append(rnd.choice(["🌿 Notas en alza: {}.", "🌿 Se está pidiendo: {}.", "🌿 Estilos que suenan: {}."]).format(_lista(notas)))
    reponer = senales.get("agotados_con_demanda", [])[:5]
    if reponer:
        out.append(rnd.choice(["📦 Reponer primero: {} (tienen demanda y no hay existencias).",
                               "📦 Con demanda y sin existencias: {}. Prioriza su compra."]).format(_lista(reponer)))
    sin = senales.get("sin_catalogo", [])[:3]
    if sin:
        out.append(rnd.choice(["🛒 Buscan y no lo tienes: {}. Evalúa traerlos.",
                               "🛒 Oportunidad de catálogo: {}."]).format(_lista(f"«{s}»" for s in sin)))
    if vendibles:
        hoy = [p["original"] for p in vendibles[:3]]
        out.append(rnd.choice(["✅ Hoy: publica en Marketplace {} y destácalos en la web.",
                               "✅ Acción de hoy: sube a Marketplace {}; súbelos también en el Top 10."]).format(_lista(hoy)))
    return "\n".join(out) or "Sin señales suficientes hoy: no hay recomendaciones nuevas."


def verificar(texto, senales, catalogo=()):
    """Lista de problemas (vacía = el informe se puede usar)."""
    problemas = []
    t = _norm(texto)
    if len(texto.strip()) < 40:
        problemas.append("demasiado corto")
    if len(texto) > 1500:
        problemas.append("demasiado largo")
    permitidos = {_norm(p.get("original")) for p in senales.get("perfumes", [])}
    permitidos |= {_norm(x) for x in senales.get("agotados_con_demanda", []) + senales.get("sin_catalogo", []) + senales.get("noticias", [])}
    for nombre in catalogo:
        n = _norm(nombre)
        # «Good girl» dentro de «Very good girl» (que sí tiene señal) no cuenta como inventado
        if len(n) >= 5 and f" {n} " in f" {t} " and not any(f" {n} " in f" {x} " for x in permitidos):
            problemas.append(f"menciona un perfume sin señal: {nombre}")
    accion = f" {_norm(next((l for l in texto.splitlines() if l.strip().startswith('✅')), ''))} "
    # Se quitan primero los vendibles (de más largo a más corto): «Mayar» no se confunde con «Mayar Cherry»
    for v in sorted((_norm(p.get("original")) for p in senales.get("perfumes", []) if p.get("vendible") is not False), key=len, reverse=True):
        if v:
            accion = accion.replace(f" {v} ", " | ")
    for p in senales.get("perfumes", []):
        if p.get("vendible") is False and _norm(p.get("original")) and f" {_norm(p['original'])} " in accion:
            problemas.append(f"manda a publicar un no vendible: {p['original']}")
    return problemas


# ---------- Generación sintética ----------

NOTAS = ["vainilla", "café", "pistacho", "chocolate", "jazmín", "rosa", "oud", "ámbar", "bergamota", "cítricos",
         "almizcle", "coco", "caramelo", "cuero", "lavanda", "pimienta rosa", "sal marina", "gourmand", "solar", "frutal"]
FUERA = ["perfume la vida es bella", "perfume tom ford", "perfume odyssey", "perfume fugazzi", "perfume nitro",
         "perfume baccarat", "perfume libre", "perfume born in roma", "perfume club de nuit untold", "perfume delina",
         "perfume angels share", "perfume hawas", "perfume amber oud", "perfume 9am", "perfume eros flame"]
TITULARES = ["Los perfumes que serán tendencia esta temporada", "La nota gourmand que conquista las redes",
             "Perfumes árabes: por qué están arrasando en Latinoamérica", "Los aromas solares, la nueva obsesión",
             "Las fragancias más regaladas del año", "El perfume viral que todos buscan en TikTok"]


def _senales_sinteticas(productos, rnd):
    # «Buscan y no tenemos» solo con perfumes que de verdad no están en el catálogo
    nombres = {_norm(p["name"]) for p in productos}
    fuera = [f for f in FUERA if not any(f" {n} " in f" {_norm(f)} " for n in nombres if len(n) >= 4)]
    elegidos = rnd.sample(productos, k=rnd.randint(3, 10))
    puntajes = sorted((rnd.randint(15, 100) for _ in elegidos), reverse=True)
    puntajes[0] = 100
    perfumes = []
    for p, s in zip(elegidos, puntajes):
        agotado = rnd.random() < 0.25
        perfumes.append({
            "original": p["name"], "marca": p.get("brand"), "puntaje": s,
            "cambio": rnd.choice([None, 0, rnd.randint(-20, 30)]), "agotado": agotado,
            "vendible": not agotado or rnd.random() < 0.5,
            "motivos": [rnd.choice([f"Buscado en Google Colombia: «perfume {p['name'].lower()}» (#{rnd.randint(1, 10)})",
                                    f"La marca {p.get('brand')} está sonando", "Notas en alza: " + ", ".join(rnd.sample(NOTAS, 2))])]
        })
    return {
        "perfumes": perfumes,
        "notas": rnd.sample(NOTAS, rnd.randint(0, 6)),
        "agotados_con_demanda": [p["original"] for p in perfumes if p["agotado"]][:5],
        "sin_catalogo": rnd.sample(fuera, min(len(fuera), rnd.randint(0, 4))),
        "noticias": rnd.sample(TITULARES, rnd.randint(0, 3)),
    }


def _malo(senales, productos, rnd, ideal):
    """Fallas típicas que el DPO debe castigar."""
    sin_senal = [p["name"] for p in productos if p["name"] not in {x["original"] for x in senales["perfumes"]}]
    no_vendibles = [p["original"] for p in senales["perfumes"] if p.get("vendible") is False]
    tipo = rnd.choice(["inventa", "no_vendible" if no_vendibles else "inventa", "saludo"])
    if tipo == "inventa":
        return ideal.replace("📈 ", f"📈 {rnd.choice(sin_senal)} lidera las ventas del mes. ", 1)
    if tipo == "no_vendible":
        return "\n".join(l for l in ideal.splitlines() if not l.startswith("✅")) + \
            f"\n✅ Hoy: publica en Marketplace {no_vendibles[0]} y ponlo primero en la web."
    return "¡Hola equipo! 😊 Espero que estén muy bien. " + ideal.split("\n")[0] + " ¡Que tengan un excelente día!"


def generar(n=400, n_dpo=160, semilla=2026, salida=None):
    salida = salida or os.path.join(AQUI, "salida")
    with open(os.path.join(salida, "rag", "conocimiento.json"), encoding="utf-8") as f:
        unicos = {}
        for p in json.load(f)["productos"]:
            if p.get("name"):
                unicos.setdefault(_norm(p["name"]), p)  # un solo producto por nombre
        productos = list(unicos.values())
    rnd = random.Random(semilla)
    nombres = [p["name"] for p in productos]
    sft, dpo = [], []
    for i in range(n + n_dpo):
        s = _senales_sinteticas(productos, rnd)
        ideal = informe_ideal(s, rnd)
        assert not verificar(ideal, s, nombres), verificar(ideal, s, nombres)
        prompt = [{"role": "system", "content": SISTEMA_ANALISTA}, {"role": "user", "content": contexto(s)}]
        if i < n:
            sft.append({"messages": prompt + [{"role": "assistant", "content": ideal}], "intencion": "analista_mercado"})
        else:
            dpo.append({"prompt": prompt, "chosen": [{"role": "assistant", "content": ideal}],
                        "rejected": [{"role": "assistant", "content": _malo(s, productos, rnd, ideal)}], "falla": "analista"})
    os.makedirs(os.path.join(salida, "analista"), exist_ok=True)
    for nombre, filas in (("analista_sft.jsonl", sft), ("analista_dpo.jsonl", dpo)):
        with open(os.path.join(salida, "analista", nombre), "w", encoding="utf-8") as f:
            for x in filas:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return len(sft), len(dpo)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--dpo", type=int, default=160)
    ap.add_argument("--semilla", type=int, default=2026)
    a = ap.parse_args()
    s, d = generar(a.n, a.dpo, a.semilla)
    print(f"Analista: {s} ejemplos SFT y {d} pares DPO en dataset_aura/salida/analista/")
