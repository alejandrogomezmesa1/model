"""
Página local para revisar respuestas de AURA y corregirlas (retroalimentación humana para el refuerzo).

Muestra las conversaciones que registró la API (data/conversaciones.jsonl: clientes reales y pruebas),
ordenadas de peor a mejor según la función de recompensa. Por cada una marcas 👍 o 👎 y, si está mal,
escribes cómo debió responder. Se guarda en data/retroalimentacion.jsonl y `src/refuerzo.py pares`
lo convierte en pares de preferencia con doble peso.

El botón «Generar pruebas» envía preguntas de la evaluación y del dataset a la API local (que debe
estar corriendo en el puerto 8000), para tener respuestas que revisar aunque no haya clientes.

Uso:  ./hf-locql/Scripts/python.exe src/revisar.py     →  abre http://127.0.0.1:8100
"""
import datetime
import json
import random
import sys
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from recompensa import Recompensa  # noqa: E402
from knowledge_db import KnowledgeBase, normalize_text  # noqa: E402

CONVERSACIONES = ROOT / "data" / "conversaciones.jsonl"
RETRO = ROOT / "data" / "retroalimentacion.jsonl"
API_LOCAL = "http://127.0.0.1:8000"
R = Recompensa()
app = FastAPI(title="Revisión de AURA")


def leer(ruta):
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def veredictos():
    """Último veredicto por conversación (el archivo solo se agrega, nunca se reescribe)."""
    return {v["id"]: v for v in leer(RETRO)}


@app.get("/api/conversaciones")
def conversaciones():
    vs = veredictos()
    filas = []
    for c in leer(CONVERSACIONES):
        genero = KnowledgeBase.detectar_genero(normalize_text(c["mensaje"]), c.get("historial"))
        p = R.puntuar(c.get("respuesta_cruda") or c["respuesta"], contexto=R.productos_del_contexto(c.get("contexto", "")),
                      genero=genero, pregunta=c["mensaje"])
        filas.append({**c, "puntos": p, "veredicto": vs.get(c["id"])})
    filas.sort(key=lambda c: (c["veredicto"] is not None, c["puntos"]["total"]))
    return filas


class Veredicto(BaseModel):
    id: str
    veredicto: str
    correccion: str = ""


@app.post("/api/veredicto")
def guardar(v: Veredicto):
    if v.veredicto not in ("buena", "mala"):
        raise HTTPException(400, "veredicto debe ser buena o mala")
    if v.veredicto == "mala" and not v.correccion.strip():
        raise HTTPException(400, "Escribe cómo debió responder AURA")
    RETRO.parent.mkdir(parents=True, exist_ok=True)
    with open(RETRO, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": v.id, "veredicto": v.veredicto, "correccion": v.correccion.strip(),
                            "fecha": datetime.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    return {"ok": True}


class Pruebas(BaseModel):
    cantidad: int = 10


@app.post("/api/pruebas")
def generar_pruebas(p: Pruebas):
    """Envía preguntas variadas a la API local; quedan registradas como origen «prueba»."""
    preguntas = [c["mensaje"] for c in leer(ROOT / "dataset_aura" / "salida" / "eval" / "aura_eval.jsonl")]
    preguntas += [e["meta"]["pregunta_limpia"] for e in leer(ROOT / "dataset_aura" / "salida" / "sft" / "aura_sft_meta.jsonl")]
    llave = (ROOT / "data" / ".api_key").read_text(encoding="utf-8").splitlines()[0].strip()
    enviadas = 0
    for q in random.sample(preguntas, min(max(1, p.cantidad), 30)):
        req = urllib.request.Request(f"{API_LOCAL}/chat", data=json.dumps({"message": q, "session_id": f"eval-{random.random()}"}).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {llave}"})
        try:
            urllib.request.urlopen(req, timeout=120).read()
            enviadas += 1
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"La API local no respondió ({e}). ¿Está corriendo en el puerto 8000?")
    return {"enviadas": enviadas}


@app.get("/", response_class=HTMLResponse)
def pagina():
    return PAGINA


PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de AURA</title>
<style>
:root { --bg:#f6f4ef; --card:#fff; --txt:#1c1b19; --sub:#6b675f; --line:#e2ddd2; --oro:#a8841f; --ok:#15803d; --mal:#b91c1c; }
@media (prefers-color-scheme: dark) { :root { --bg:#121214; --card:#1b1b1e; --txt:#ece9e1; --sub:#9a968c; --line:#2c2c30; --oro:#d4af37; --ok:#4ade80; --mal:#f87171; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--txt); font:15px/1.5 system-ui, sans-serif; }
header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:12px 16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; z-index:1 }
h1 { font-size:18px; margin:0; margin-right:auto } main { max-width:900px; margin:0 auto; padding:16px; }
button, select { font:inherit; padding:6px 12px; border:1px solid var(--line); background:var(--card); color:var(--txt); border-radius:6px; cursor:pointer }
button.primario { background:var(--oro); color:#000; border-color:var(--oro) } button:disabled { opacity:.5; cursor:default }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:14px }
.meta { color:var(--sub); font-size:13px; display:flex; gap:10px; flex-wrap:wrap } .q { font-weight:600; margin:6px 0 }
.r { white-space:pre-wrap; background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:10px; margin:8px 0 }
.fallas { color:var(--mal); font-size:13px } .hecho { color:var(--ok); font-size:13px }
textarea { width:100%; min-height:110px; font:inherit; padding:8px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--txt) }
.acciones { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px } .vacio { color:var(--sub); text-align:center; padding:40px }
</style></head><body>
<header><h1>Revisión de AURA</h1><span id="cuenta" class="meta"></span>
<select id="filtro"><option value="pendientes">Pendientes</option><option value="revisadas">Revisadas</option><option value="todas">Todas</option></select>
<select id="origen"><option value="">Clientes y pruebas</option><option value="cliente">Solo clientes</option><option value="prueba">Solo pruebas</option></select>
<button id="generar">Generar 10 pruebas</button></header>
<main id="lista"><p class="vacio">Cargando…</p></main>
<script>
let datos = [];
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? '').replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function cargar() { datos = await (await fetch('/api/conversaciones')).json(); pintar(); }
function pintar() {
  const f = $('#filtro').value, o = $('#origen').value;
  const vis = datos.filter((c) => (f === 'todas' || (f === 'pendientes') === !c.veredicto) && (!o || c.origen === o));
  $('#cuenta').textContent = `${datos.filter((c) => !c.veredicto).length} pendientes · ${datos.filter((c) => c.veredicto).length} revisadas`;
  if (!vis.length) { $('#lista').innerHTML = '<p class="vacio">No hay conversaciones aquí. Usa «Generar 10 pruebas» o espera mensajes de clientes.</p>'; return; }
  $('#lista').innerHTML = vis.map((c) => {
    const fallas = Object.entries(c.puntos.detalle).filter(([, v]) => v < 0).map(([k]) => k);
    const v = c.veredicto;
    return `<div class="card" data-id="${c.id}">
      <div class="meta"><span>${esc(c.fecha)}</span><span>${c.origen}</span><span>recompensa ${c.puntos.total}</span><span>${c.segundos}s</span></div>
      ${(c.historial || []).map((m) => `<div class="meta">${m.role === 'user' ? 'Cliente' : 'AURA'}: ${esc(m.content).slice(0, 160)}</div>`).join('')}
      <div class="q">Cliente: ${esc(c.mensaje)}</div>
      <div class="r">${esc(c.respuesta)}</div>
      ${fallas.length ? `<div class="fallas">Reglas que falla: ${fallas.join(', ')}</div>` : ''}
      ${v ? `<div class="hecho">${v.veredicto === 'buena' ? '👍 Marcada como buena' : '👎 Corregida: ' + esc(v.correccion)}</div>` : ''}
      <div class="acciones"><button data-a="buena">👍 Buena</button><button data-a="mala">👎 Mala, corregir</button></div>
      <div class="editor" hidden><p class="meta">Escribe cómo debió responder AURA (puedes editar la respuesta):</p>
        <textarea>${esc(c.respuesta)}</textarea>
        <div class="acciones"><button class="primario" data-a="guardar">Guardar corrección</button><button data-a="cancelar">Cancelar</button></div></div>
    </div>`;
  }).join('');
}
async function enviar(id, veredicto, correccion = '') {
  const r = await fetch('/api/veredicto', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, veredicto, correccion }) });
  if (!r.ok) { alert((await r.json()).detail); return; }
  datos.find((c) => c.id === id).veredicto = { veredicto, correccion };
  pintar();
}
$('#lista').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  const card = b.closest('.card'), id = card.dataset.id, ed = card.querySelector('.editor');
  if (b.dataset.a === 'buena') enviar(id, 'buena');
  if (b.dataset.a === 'mala') ed.hidden = false;
  if (b.dataset.a === 'cancelar') ed.hidden = true;
  if (b.dataset.a === 'guardar') enviar(id, 'mala', card.querySelector('textarea').value);
});
$('#filtro').onchange = pintar; $('#origen').onchange = pintar;
$('#generar').onclick = async () => {
  const b = $('#generar'); b.disabled = true; b.textContent = 'Generando…';
  const r = await fetch('/api/pruebas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cantidad: 10 }) });
  if (!r.ok) alert((await r.json()).detail);
  b.disabled = false; b.textContent = 'Generar 10 pruebas'; cargar();
};
cargar();
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    print("Revisión de AURA en http://127.0.0.1:8100")
    uvicorn.run(app, host="127.0.0.1", port=8100)
