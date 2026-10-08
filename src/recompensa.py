"""
Función de recompensa de AURA: puntúa una respuesta con reglas comprobables.

Se usa para el refuerzo (elegir la mejor y la peor de varias respuestas del modelo y entrenar DPO
con esos pares) y para la evaluación local. Más alto = mejor. Cada componente queda en el detalle
para poder explicar por qué una respuesta ganó o perdió.

Reglas (penalizaciones):
  · filtraciones y fallas de negocio: las reglas del validador del dataset y de la evaluación
    (costos, proveedores, recetas, 33 %, cantidades de formulación, «original», cupones, tarjeta, Efecty…)
  · productos en negrita que no existen, con precio distinto al real o del género contrario al pedido
  · productos recomendados que no estaban en el contexto (posible invención)
  · kits en negrita, respuesta vacía, demasiado larga o corta, líneas repetidas
  · otro idioma (inglés o caracteres no latinos)
  · volver a preguntar «¿para hombre o para mujer?» cuando el cliente ya lo dijo
Premios:
  · parecido con la respuesta de referencia (F1 de palabras), cuando la hay
  · patrones que una buena respuesta debe incluir (casos de evaluación)
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dataset_aura"))
from validar_dataset import REGLAS  # noqa: E402
from aura_conocimiento import CIUDADES_NACIONALES, NEGOCIO  # noqa: E402

# Tarifa de envío correcta según el lugar que se menciona (Medellín 15.000, Área Metropolitana 20.000, resto 22.000)
TARIFA_LUGAR = [(lugar, "22.000") for lugar in CIUDADES_NACIONALES] + \
               [(lugar, "20.000") for lugar in NEGOCIO["municipios_metro"]] + [("Medellín", "15.000")]
TARIFAS = {"15.000", "20.000", "22.000"}

PROHIBIDO_EXTRA = [
    r'(?i)\beres aura, asesora olfativa', r'(?i)reglas\s*\n\s*1\.', r'\b33\s?%',
    r'(?i)\d+\s?(a \d+\s?)?semanas|\d+\s?°\s?C\b|alcohol (de |a )?\d+\s?°|\d+\s?grados',
    r'(?i)(aceptamos|recibimos|pagar con|pago con|puedes pagar)[^.\n]{0,60}efecty',
]
LINEA_PROD = re.compile(r'^\s*[-*•]\s*\*\*(.+?)\*\*([^\n]*)', re.M)
PRECIO = re.compile(r'\$\s?([\d.]+)')
PIDE_GENERO = re.compile(r'(?i)(para )?hombre o (para )?mujer|para (él|el) o para ella|dama o caballero')
NO_LATINO = re.compile(r'[Ѐ-ӿ֐-ۿऀ-ॿ぀-ヿ㐀-鿿가-힯]')
INGLES = re.compile(r'\b(the|and|you|your|with|please|which|would|price|here|this)\b', re.I)
VACIAS = set('de la el los las un una y o a en con para por que se lo le es son su sus al del mas muy te tu mi'.split())


def clave(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', s)


def palabras(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn')
    return [w for w in re.findall(r'[a-z0-9]+', s) if len(w) > 2 and w not in VACIAS]


def f1(a, b):
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb:
        return 0.0
    comunes = sum(min(pa.count(w), pb.count(w)) for w in set(pa))
    if not comunes:
        return 0.0
    p, r = comunes / len(pa), comunes / len(pb)
    return 2 * p * r / (p + r)


class Recompensa:
    def __init__(self, conocimiento_path=None):
        ruta = conocimiento_path or ROOT / "dataset_aura" / "salida" / "rag" / "conocimiento.json"
        con = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self.productos = {clave(p["name"]): p for p in con["productos"]}
        self.kits = {clave(k["nombre"]) for k in con["kits"]}
        self.prohibidas = [(n, re.compile(p)) for n, p in REGLAS] + \
                          [(f"extra{i}", re.compile(p)) for i, p in enumerate(PROHIBIDO_EXTRA)]

    @staticmethod
    def productos_del_contexto(sistema: str) -> set:
        """Nombres (clave) de las filas del bloque «CATÁLOGO RELEVANTE» del prompt de sistema."""
        if "CATÁLOGO RELEVANTE:" not in sistema:
            return set()
        bloque = sistema.split("CATÁLOGO RELEVANTE:", 1)[1].split("\n\n", 1)[0]
        return {clave(l.split(" | ")[0]) for l in bloque.strip().splitlines() if " | " in l}

    def puntuar(self, respuesta: str, *, contexto: set = None, genero: str = None, pregunta: str = None,
                referencia: str = None, debe_incluir=(), no_debe_incluir=()) -> dict:
        r = respuesta or ""
        d = {}

        def sumar(k, v):
            d[k] = round(d.get(k, 0) + v, 3)

        if not r.strip():
            sumar("vacia", -5)
        for nombre, patron in self.prohibidas:
            if patron.search(r):
                sumar(f"prohibido:{nombre}", -3)
        for patron in no_debe_incluir:
            if re.search(patron, r):
                sumar("prohibido:eval", -3)
        for m in LINEA_PROD.finditer(r):
            k = clave(m.group(1))
            if k in self.kits:
                sumar("kit_en_negrita", -1)
                continue
            p = self.productos.get(k)
            if not p:
                sumar("producto_inexistente", -2)
                continue
            mp = PRECIO.search(m.group(2))
            if mp and int(re.sub(r'\D', '', mp.group(1)) or 0) != p["price"]:
                sumar("precio_incorrecto", -2)
            if contexto is not None and k not in contexto:
                sumar("fuera_de_contexto", -0.5)
            if genero in ("Masculino", "Femenino") and p["gender"] not in (genero, "Unisex"):
                sumar("genero_contrario", -2)
        if NO_LATINO.search(r):
            sumar("otro_idioma", -3)
        elif len(INGLES.findall(r)) > 3:
            sumar("ingles", -2)
        if len(r) > 1400:
            sumar("larga", -1)
        elif 0 < len(r.strip()) < 20:
            sumar("corta", -1)
        lineas = [l.strip() for l in r.splitlines() if len(l.strip()) > 15]
        if len(lineas) != len(set(lineas)):
            sumar("repetida", -1)
        if genero and PIDE_GENERO.search(r):
            sumar("pregunta_genero_ya_dicho", -1)
        if pregunta:
            # Envío a un lugar concreto: la tarifa que da debe ser la de ese lugar
            tarifas = TARIFAS & set(re.findall(r'\$\s?(\d{2}\.000)', r))
            for lugar, tarifa in TARIFA_LUGAR:
                if clave(lugar) in clave(pregunta) and tarifas and tarifa not in tarifas:
                    sumar("tarifa_envio_incorrecta", -2)
                    break
        if referencia:
            sumar("parecido_referencia", round(3 * f1(r, referencia), 3))
        for patron in debe_incluir:
            sumar("incluye" if re.search(patron, r, re.M) else "falta", 1 if re.search(patron, r, re.M) else -1)
        return {"total": round(sum(d.values()), 3), "detalle": d}
