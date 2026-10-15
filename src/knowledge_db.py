"""
Motor Híbrido de Base de Conocimiento (SQLite FTS5 + Fuzzy Matching + Fallback Vectorial)
Arquitectura de 4 Capas:
1. SQLite como fuente de verdad:
   Tabla 'productos' con: id, nombre, marca, categoria, genero, precio, ml, envase, duracion_piel, descripcion_olfativa, uso_recomendado.
2. Capa de resolución exacta primero:
   Match exacto o fuzzy con rapidfuzz contra nombre/marca en SQLite (resuelve 70-80% de casos sin vectores).
3. Vectorial solo como fallback semántico:
   Si fuzzy < 75 (ej. 'algo dulce y fresco para verano'), vectoriza la consulta y busca por similitud de coseno
   sobre los embeddings de las descripciones olfativas, recuperando el id real de SQLite.
4. El LLM solo redacta, nunca inventa campos:
   Extractive rendering inyecta los datos duros verificables directamente desde SQLite.
"""

import os
import re
import sys
import json
import sqlite3
import unicodedata
from pathlib import Path
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Intentar importar rapidfuzz y sentence_transformers
try:
    from rapidfuzz import fuzz, process, utils as rf_utils
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_VECTORS = True
except ImportError:
    HAS_VECTORS = False


def normalize_text(text: str) -> str:
    """Normaliza texto eliminando acentos y puntuación para comparaciones deterministas."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("utf-8").lower()
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


STOPWORDS = {
    # Saludos y cortesía
    "hola", "buenas", "buenos", "dias", "tardes", "noches", "saludos", "hey", "ola",
    "por", "favor", "gracias", "muchas", "ok", "vale", "bueno", "si", "no", "claro",
    # Preguntas de precio y catálogo
    "cuanto", "cuanta", "cuantos", "cuantas", "cuesta", "cuestan", "vale", "valen",
    "precio", "precios", "costo", "costos", "valor", "valores", "cotizacion", "cotizar",
    "comprar", "ordenar", "pedido", "pagar", "vender", "venden", "vendes", "vende",
    # Verbos de consulta y pronombres
    "que", "cual", "cuales", "quien", "quienes", "como", "donde", "cuando",
    "es", "son", "era", "eran", "ser", "estar", "tiene", "tienen", "tienes", "hay",
    "dime", "cuenta", "cuentame", "explicame", "muestra", "muestrame", "mostrar",
    "info", "informacion", "detalle", "detalles", "ficha", "caracteristicas", "notas",
    "quiero", "quisiera", "deseo", "gustaria", "saber", "conocer", "buscar",
    # Pronombres y complementos
    "me", "te", "se", "nos", "les", "le",
    # Preposiciones y artículos
    "de", "del", "el", "la", "los", "las", "un", "una", "unos", "unas", "al", "en",
    "con", "para", "sobre", "y", "o", "a", "mi", "tu", "su", "este", "esta", "estos", "estas",
    # Indefinidos
    "algo", "algun", "alguna", "algunos", "algunas", "otro", "otra", "otros", "otras",
    # Términos generales de perfumería
    "perfume", "perfumes", "fragancia", "fragancias", "marca", "marcas",
    "colonia", "colonias", "locion", "lociones", "aroma", "aromas", "olor", "olores",
    # Verbos genéricos de consulta y recomendación
    "sirve", "sirven", "funciona", "funcionan", "hace", "hacen", "usar", "usa", "usan",
    "utiliza", "utilizan", "aplicar", "aplica", "recomienda", "recomiendan", "recomiendas",
    "recomiendame", "recomendacion", "recomendaciones", "sugieres", "sugiere", "sugerencia",
    "sugerencias", "opcion", "opciones", "manejan", "tienen", "venden"
}


DURACION_PIEL = "8 a 12 horas en piel (según el tipo de piel)"

# Género pedido por el cliente (texto normalizado, sin tildes). Unisex primero: «unisex para hombre» es unisex.
PATRONES_GENERO = [
    ("Unisex", r"\b(unisex|ambos|para los dos|compartir)\b"),
    ("Masculino", r"\b(hombres?|caballeros?|masculinos?|varon|varones|novio|esposo|papa|padre|hijo|hermano|abuelo|chico|man|men)\b"),
    ("Femenino", r"\b(mujer|mujeres|damas?|femeninos?|femenina|ella|novia|esposa|mama|madre|hija|hermana|abuela|chica|woman|women)\b"),
]
GENERO_PALABRA = {"Masculino": "hombre", "Femenino": "mujer", "Unisex": "unisex"}

KNOWN_BRANDS = [
    ("carolina herrera", "Carolina Herrera"),
    ("carolina", "Carolina Herrera"),
    ("bharara", "Bharara"),
    ("dior", "Dior"),
    ("tom ford", "Tom Ford"),
    ("lattafa", "Lattafa"),
    ("xerjoff", "Xerjoff"),
    ("afnan", "Afnan"),
    ("creed", "Creed"),
    ("le laboo", "Le Labo"),
    ("le labo", "Le Labo"),
    ("labo", "Le Labo"),
    ("rasasi", "Rasasi"),
    ("al haramain", "Al Haramain"),
    ("chanel", "Chanel"),
    ("armaf", "Armaf"),
    ("versace", "Versace"),
    ("paco rabanne", "Paco Rabanne"),
    ("jean paul gaultier", "Jean Paul Gaultier"),
    ("louis vuitton", "Louis Vuitton"),
    ("ariana grande", "Ariana Grande"),
    ("hugo boss", "Hugo Boss"),
    ("yves saint laurent", "YSL"),
    ("ysl", "YSL"),
    ("giorgio armani", "Armani"),
    ("armani", "Armani"),
    ("burberry", "Burberry"),
    ("parfums de marly", "Parfums de Marly"),
    ("calvin klein", "Calvin Klein"),
    ("lancome", "Lancôme")
]


class KnowledgeBase:
    def __init__(self, db_path=None):
        project_root = Path(__file__).resolve().parent.parent
        self.data_dir = project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if db_path is None:
            self.db_path = str(self.data_dir / "perfumes_db.sqlite")
        else:
            self.db_path = str(db_path)

        self.overrides_path = str(self.data_dir / "overrides.json")
        self.embeddings_path = str(self.data_dir / "product_embeddings.npy")
        self.embeddings_ids_path = str(self.data_dir / "product_embeddings_ids.json")

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

        # Cache en memoria para Fuzzy Matching ultrarrápido (<1ms)
        self._product_names_cache = []
        self._product_ids_cache = []
        self._load_fuzzy_cache()

        # Modelo vectorial para fallback semántico (lazy loaded para no demorar arranque)
        self._vector_model = None
        self._cached_embeddings = None
        self._cached_emb_ids = None

    def _init_schema(self):
        """Inicializa la tabla 'productos' y las tablas auxiliares en SQLite."""
        cur = self.conn.cursor()
        # Bases creadas con el esquema anterior (sin la columna 'contexto') se recrean en build_from_sources
        cur.execute("PRAGMA table_info(productos)")
        cols = {r[1] for r in cur.fetchall()}
        if cols and "contexto" not in cols:
            cur.execute("DROP TABLE productos")
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nombre_norm TEXT NOT NULL,
            marca TEXT NOT NULL,
            marca_norm TEXT NOT NULL,
            categoria TEXT,
            genero TEXT,
            precio REAL,
            ml TEXT,
            envase TEXT,
            duracion_piel TEXT,
            descripcion_olfativa TEXT,
            uso_recomendado TEXT,
            busqueda_norm TEXT,
            top10 INTEGER,
            agotado INTEGER DEFAULT 0,
            url TEXT,
            contexto TEXT
        );

        CREATE TABLE IF NOT EXISTS bloques_contexto (
            clave TEXT PRIMARY KEY,
            texto TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS guias_tecnicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta TEXT NOT NULL,
            pregunta_norm TEXT NOT NULL,
            respuesta TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS top10 (
            posicion INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            categoria TEXT,
            genero TEXT,
            precio REAL
        );

        CREATE TABLE IF NOT EXISTS envases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            material TEXT,
            descripcion TEXT
        );

        CREATE TABLE IF NOT EXISTS kits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            precio REAL,
            descripcion TEXT
        );

        CREATE TABLE IF NOT EXISTS overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_key TEXT UNIQUE NOT NULL,
            chosen_response TEXT NOT NULL,
            campo_modificado TEXT,
            timestamp TEXT NOT NULL
        );
        """)
        self.conn.commit()

    def _load_fuzzy_cache(self):
        """Carga en memoria los nombres y marcas normalizados para rapidfuzz."""
        cur = self.conn.cursor()
        cur.execute("SELECT id, nombre, marca FROM productos ORDER BY id ASC")
        rows = cur.fetchall()
        self._product_names_cache = [f"{r['nombre']} {r['marca']}" for r in rows]
        self._product_ids_cache = [r['id'] for r in rows]

    def _extract_brand(self, nombre: str, categoria: str = "") -> str:
        """Determina la casa o marca a partir del nombre o texto."""
        norm = normalize_text(nombre)
        for key, display in KNOWN_BRANDS:
            if re.search(r'\b' + re.escape(key) + r'\b', norm):
                return display
        # Fallback al primer término del nombre
        first_token = nombre.split()[0].capitalize() if nombre.strip() else "Alta Densidad"
        return first_token

    def build_from_sources(self, conocimiento_path=None):
        """Indexa el catálogo ACTUAL de la tienda (dataset_aura/salida/rag/conocimiento.json) en SQLite.

        Solo entran productos que la tienda vende: nada de «clásicos» de dataset_perfumeria.csv
        ni guías de formulación con cantidades (la concentración y la receta son confidenciales).
        """
        if conocimiento_path is None:
            conocimiento_path = self.data_dir.parent / "dataset_aura" / "salida" / "rag" / "conocimiento.json"
        with open(conocimiento_path, "r", encoding="utf-8") as f:
            con = json.load(f)

        cur = self.conn.cursor()
        for tabla in ("productos", "guias_tecnicas", "top10", "envases", "kits", "bloques_contexto"):
            cur.execute(f"DELETE FROM {tabla}")

        for p in con["productos"]:
            notas = p.get("notes", {})
            acordes = ", ".join(p.get("accords", [])[:6])
            desc = (f"Acordes: {acordes}. Salida: {', '.join(notas.get('top', []))}. "
                    f"Corazón: {', '.join(notas.get('heart', []))}. Fondo: {', '.join(notas.get('base', []))}.")
            busqueda = normalize_text(" ".join([p["name"], p["brand"], p["gender"], p["category"], acordes,
                                                " ".join(p.get("families", [])), desc]))
            cur.execute("""
            INSERT INTO productos (id, nombre, nombre_norm, marca, marca_norm, categoria, genero, precio, ml, envase,
                                   duracion_piel, descripcion_olfativa, uso_recomendado, busqueda_norm, top10, agotado, url, contexto)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p["id"], p["name"], normalize_text(p["name"]), p["brand"], normalize_text(p["brand"]), p["category"],
                  p["gender"], float(p["price"]), ", ".join(p.get("sizes", [])) or "100ml", "Vidrio", DURACION_PIEL, desc,
                  "Aplicar sobre piel hidratada en puntos de pulso (cuello, pecho, muñecas) sin frotar.",
                  busqueda, p.get("top10"), int(bool(p.get("agotado"))), p.get("url"), p["contexto"]))
            if p.get("top10"):
                cur.execute("INSERT INTO top10 (posicion, nombre, categoria, genero, precio) VALUES (?, ?, ?, ?, ?)",
                            (p["top10"], p["name"], p["category"], p["gender"], float(p["price"])))

        for e in con.get("crea_tu_perfume", {}).get("envases", []):
            cur.execute("INSERT INTO envases (nombre, material, descripcion) VALUES (?, ?, ?)",
                        (e["name"], e.get("material", "Vidrio"), e.get("description", "")))
        for k in con.get("kits", []):
            cur.execute("INSERT INTO kits (nombre, precio, descripcion) VALUES (?, ?, ?)",
                        (k["nombre"], float(k["precio"]), k.get("resumen", "")))
        for clave, texto in con.get("contextos", {}).items():
            cur.execute("INSERT INTO bloques_contexto (clave, texto) VALUES (?, ?)", (clave, texto))

        self.conn.commit()
        self._load_overrides_from_file()
        self._load_fuzzy_cache()
        self._precompute_embeddings()
        print(f"Base de conocimiento indexada: {len(con['productos'])} perfumes, {len(con.get('kits', []))} kits → {self.db_path}")

    # =========================================================================
    # CONTEXTO RAG PARA EL MODELO (mismo formato que el dataset de entrenamiento)
    # =========================================================================
    def contexto(self, query: str, history: list = None, max_productos: int = 6) -> tuple:
        """Devuelve (bloques de contexto, productos usados) para anexar al prompt de sistema de AURA.

        Los bloques usan exactamente el formato del entrenamiento: «CATÁLOGO RELEVANTE:», «KITS:»
        y «CREA TU PERFUME:».
        """
        q_norm = normalize_text(query)
        bloques, productos = [], []
        genero = self.detectar_genero(q_norm, history)

        # «Dame otros 3», «que sean distintos a estos que me repites»: fuera lo que AURA ya mostró
        mostrados = set()
        pide_otros = re.search(r"\b(otr[oa]s|distint[oa]s?|diferentes?|mas opciones|repit\w*|repetid\w*)\b", q_norm)
        if pide_otros and history:
            for m in history:
                if m.get("role") == "assistant":
                    mostrados |= {normalize_text(n) for n in re.findall(r"\*\*(.+?)\*\*", m.get("content", ""))}
        limite = max_productos + len(mostrados)

        res = self.search(query, history, limite=limite, genero=genero)
        if mostrados and (res.get("source") == "vector_fallback" or res.get("type") in ("none", "greeting")):
            # La queja sola no dice qué buscar: se repite el último pedido del cliente que sí lo decía
            for m in reversed(history):
                if m.get("role") == "user":
                    anterior = self.search(m.get("content", ""), history, limite=limite, genero=genero)
                    if anterior.get("type") in ("multi_product", "recommendation", "similar", "brand_catalog"):
                        res = anterior
                        break
        # «Pero solo de hombre» después de «algo similar a la Santal» o «perfumes amaderados»: se repite
        # esa búsqueda con el género nuevo en lugar de dar los favoritos genéricos de ese género
        if history and self._solo_genero(q_norm) and (
                res.get("type") in ("none", "recommendation") or res.get("source") == "vector_fallback"):
            for m in reversed(history):
                if m.get("role") == "user" and self._pide_estilo(normalize_text(m.get("content", ""))):
                    anterior = self.search(m.get("content", ""), None, limite=limite, genero=genero)
                    if anterior.get("type") == "similar" or str(anterior.get("source", "")).startswith("olfactory_"):
                        res = anterior
                    break
        # Pedidos por género sin perfume, marca ni familia concretos («perfumes de hombre») caen en el
        # respaldo vectorial, que no sabe de género: se responden con los favoritos de ese género.
        # Si además pide un estilo («algo fresco para hombre»), se conservan las coincidencias del vector
        # (filtradas por género más abajo); si solo dice el género, se usan los favoritos.
        if genero and (res.get("type") == "none" or (
                res.get("source") == "vector_fallback" and not self._pide_estilo(q_norm))):
            res = self.get_recommendations(q_norm + " " + GENERO_PALABRA[genero])
        data = res.get("data")
        if res.get("type") == "override":
            data = None
        # El respaldo vectorial siempre devuelve algo: en preguntas de política o cultura general solo mete ruido
        if res.get("source") == "vector_fallback" and re.search(
                r"\b(envio\w*|domicilio|pag\w+|nequi|pse|tarjeta|devol\w*|reclam\w*|factura|pedido|direccion|ubicad\w*|"
                r"horario|whatsapp|asesor|macera\w*|fijador\w*|piramide|alcohol|turbi\w*|guard\w*|concentracion|"
                r"originales?|replicas?|feromonas?|duran?|descuentos?|cupon\w*|hola|gracias|quien eres|"
                r"legal\w*|segur[oa]s?|confiab\w*|confianza|estafa\w*)\b", q_norm):
            data = None
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get("id") is None and d.get("nombre"):
                    # Filas del top 10 no traen id: se resuelven por nombre
                    d = self._producto_por_nombre(d["nombre"])
                if isinstance(d, dict) and d.get("contexto") and d["id"] not in {p["id"] for p in productos} \
                        and normalize_text(d["nombre"]) not in mostrados:
                    productos.append(d)
        if res.get("type") == "brand_catalog":
            # «Háblame de Lacoste»: el género solo filtra si lo dice esta pregunta, no uno heredado del historial
            genero = self.detectar_genero(q_norm)
        if genero and res.get("type") != "product_card":
            # Nunca se le pasan al modelo perfumes del género contrario: un modelo pequeño los recomienda igual.
            # Si el cliente nombró un perfume concreto (product_card), se respeta aunque sea de otro género.
            productos = [p for p in productos if self._genero_compatible(p.get("genero"), genero)]
            if len(productos) < 3:
                extra = self.get_recommendations(GENERO_PALABRA[genero], limite=limite).get("data") or []
                productos += [p for p in extra if p["id"] not in {x["id"] for x in productos}
                              and self._genero_compatible(p.get("genero"), genero)
                              and normalize_text(p["nombre"]) not in mostrados]
        productos = productos[:max_productos]
        if productos:
            bloques.append("CATÁLOGO RELEVANTE:\n" + "\n".join(p["contexto"] for p in productos))

        if re.search(r"\b(kits?|combos?|sets?|estuches?|miniaturas?)\b", q_norm):
            bloques.append(self._bloque("kits"))
        if re.search(r"\b(crea|crear|armar|arma|personaliz\w*|envases?|frascos?|botellas?)\b", q_norm):
            bloques.append(self._bloque("crea_tu_perfume"))
        return "\n\n".join(b for b in bloques if b), productos

    @staticmethod
    def detectar_genero(q_norm: str, history: list = None):
        """'Masculino', 'Femenino', 'Unisex' o None, según la pregunta o, si no lo dice, los últimos mensajes del cliente."""
        textos = [q_norm] + [normalize_text(m.get("content", "")) for m in reversed(history or [])
                             if m.get("role") == "user"][:2]
        for t in textos:
            for genero, patron in PATRONES_GENERO:
                if re.search(patron, t):
                    return genero
        return None

    @staticmethod
    def _pide_estilo(q_norm: str) -> bool:
        """True si la pregunta trae algo más que el género (un estilo, ocasión o nota)."""
        resto = q_norm
        for _, patron in PATRONES_GENERO:
            resto = re.sub(patron, " ", resto)
        palabras = [w for w in resto.split() if w not in STOPWORDS and len(w) > 2
                    and w not in {"busco", "buscando", "regalo", "regalar", "mis", "uno", "unos"}]
        return bool(palabras)

    @staticmethod
    def _solo_genero(q_norm: str) -> bool:
        """True si la pregunta solo precisa el género («pero solo de hombre», «y para mujer?»)."""
        resto = q_norm
        for _, patron in PATRONES_GENERO:
            resto = re.sub(patron, " ", resto)
        if resto == q_norm:  # no nombra ningún género
            return False
        relleno = {"pero", "solo", "solamente", "unicamente", "mejor", "ahora", "entonces", "sean", "sea", "y", "pues", "porfa"}
        return not [w for w in resto.split() if w not in STOPWORDS and w not in relleno]

    @staticmethod
    def _genero_compatible(genero_producto, genero_pedido) -> bool:
        g = (genero_producto or "").lower()
        if genero_pedido == "Unisex":
            return "unisex" in g
        return "unisex" in g or genero_pedido.lower() in g

    def _bloque(self, clave: str) -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT texto FROM bloques_contexto WHERE clave = ?", (clave,))
        row = cur.fetchone()
        return row["texto"] if row else ""

    def _producto_por_nombre(self, nombre: str):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM productos WHERE nombre_norm = ?", (normalize_text(nombre),))
        row = cur.fetchone()
        return dict(row) if row else None

    def catalogo_precios(self) -> dict:
        """{nombre normalizado: (nombre, precio)} para verificar las líneas «- **Nombre**: $precio» de la respuesta."""
        cur = self.conn.cursor()
        cur.execute("SELECT nombre, precio FROM productos")
        return {normalize_text(r["nombre"]): (r["nombre"], r["precio"]) for r in cur.fetchall()}

    def urls_productos(self) -> set:
        """Enlaces reales de las fichas de perfume, para borrar los que el modelo invente."""
        cur = self.conn.cursor()
        cur.execute("SELECT url FROM productos WHERE url IS NOT NULL AND url <> ''")
        return {r["url"] for r in cur.fetchall()}

    def nombres_kits(self) -> set:
        cur = self.conn.cursor()
        cur.execute("SELECT nombre FROM kits")
        return {normalize_text(r["nombre"]) for r in cur.fetchall()}

    # =========================================================================
    # PRECOMPUTACIÓN DE EMBEDDINGS (CAPA VECTORIAL DE FALLBACK)
    # =========================================================================
    def _precompute_embeddings(self):
        """Genera y guarda en disco los embeddings de la columna descripcion_olfativa."""
        if not HAS_VECTORS:
            print("sentence-transformers no disponible, omitiendo precomputación de embeddings.")
            return

        cur = self.conn.cursor()
        cur.execute("SELECT id, nombre, marca, categoria, descripcion_olfativa, uso_recomendado FROM productos ORDER BY id ASC")
        rows = cur.fetchall()
        if not rows:
            return

        print(f"Precomputando embeddings semánticos para {len(rows)} productos...")
        model = self._get_vector_model()
        texts = [f"{r['nombre']} {r['marca']} {r['categoria']}: {r['descripcion_olfativa']} {r['uso_recomendado']}" for r in rows]
        ids = [r['id'] for r in rows]

        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        np.save(self.embeddings_path, embeddings)
        with open(self.embeddings_ids_path, "w", encoding="utf-8") as f:
            json.dump(ids, f)
        
        self._cached_embeddings = embeddings
        self._cached_emb_ids = ids
        print(f"Embeddings guardados en: {self.embeddings_path}")

    def _get_vector_model(self):
        if self._vector_model is None and HAS_VECTORS:
            self._vector_model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._vector_model

    def _load_cached_embeddings(self):
        if self._cached_embeddings is None and os.path.exists(self.embeddings_path) and os.path.exists(self.embeddings_ids_path):
            try:
                self._cached_embeddings = np.load(self.embeddings_path)
                with open(self.embeddings_ids_path, "r", encoding="utf-8") as f:
                    self._cached_emb_ids = json.load(f)
            except Exception as e:
                print(f"Error cargando embeddings en caché: {e}")

    # =========================================================================
    # PERSISTENCIA Y CONSULTA DE OVERRIDES ('corregir:')
    # =========================================================================
    def _load_overrides_from_file(self):
        if not os.path.exists(self.overrides_path):
            return
        try:
            with open(self.overrides_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            cur = self.conn.cursor()
            for key, val in overrides.items():
                cur.execute("""
                INSERT OR REPLACE INTO overrides (target_key, chosen_response, campo_modificado, timestamp)
                VALUES (?, ?, ?, datetime('now'))
                """, (normalize_text(key), val.get("response", ""), val.get("field", "general")))
            self.conn.commit()
        except Exception as e:
            print(f"Error cargando overrides: {e}")

    def save_override(self, target_key: str, chosen_response: str, field: str = "general"):
        norm_key = normalize_text(target_key)
        cur = self.conn.cursor()
        cur.execute("""
        INSERT OR REPLACE INTO overrides (target_key, chosen_response, campo_modificado, timestamp)
        VALUES (?, ?, ?, datetime('now'))
        """, (norm_key, chosen_response, field))
        self.conn.commit()

        overrides_dict = {}
        if os.path.exists(self.overrides_path):
            try:
                with open(self.overrides_path, "r", encoding="utf-8") as f:
                    overrides_dict = json.load(f)
            except Exception:
                overrides_dict = {}

        overrides_dict[norm_key] = {
            "target": target_key,
            "response": chosen_response,
            "field": field
        }
        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump(overrides_dict, f, ensure_ascii=False, indent=2)

    def check_override(self, query: str):
        norm_q = normalize_text(query)
        cur = self.conn.cursor()
        cur.execute("SELECT chosen_response FROM overrides WHERE target_key = ?", (norm_q,))
        row = cur.fetchone()
        # Solo la pregunta exacta (normalizada). Antes también valía la coincidencia parcial y una pregunta
        # corta como «king» o «rosa» devolvía una corrección vieja sin pasar por el modelo.
        return row["chosen_response"] if row else None

    # =========================================================================
    # MOTOR DE BÚSQUEDA HÍBRIDO (EXACTO -> FUZZY -> VECTORIAL FALLBACK)
    # =========================================================================
    def search(self, query: str, history: list = None, limite: int = 4, genero=None) -> dict:
        """
        Flujo de búsqueda en 4 etapas:
        1. Overrides prioritarios.
        2. Intenciones fijas (Top 10, Envases, Kits, Química).
        3. Capa 1: Coincidencia Exacta y Fuzzy String (rapidfuzz) contra 'productos'.
        4. Capa 2: Fallback Vectorial Semántico sobre 'descripcion_olfativa'.
        """
        # 1. Override prioritario
        override = self.check_override(query)
        if override:
            return {"type": "override", "content": override, "data": None, "rendered": override}

        q_norm = normalize_text(query)

        # 2. Manejo de Saludos Directos (evita heredar términos de búsquedas anteriores)
        GREETINGS = {"hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "saludos", "hey", "ola", "que tal", "buen dia", "hola buenas"}
        if q_norm in GREETINGS:
            return {
                "type": "greeting",
                "data": None,
                "rendered": "¡Hola! 👋 Soy AURA, tu asesora olfativa de Fragancias de Alta Densidad. ¿Buscas un perfume para ti o para regalar? Cuéntame qué aromas te gustan y te recomiendo."
            }

        q_words = [w for w in q_norm.split() if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]

        # Contexto previo para respuestas breves ("Si", "Claro", "Ok")
        if not q_words and history:
            for prev in reversed(history):
                if prev.get("role") == "user":
                    p_norm = normalize_text(prev.get("content", ""))
                    if p_norm not in GREETINGS:
                        p_words = [w for w in p_norm.split() if w not in STOPWORDS and len(w) > 1]
                        if p_words:
                            q_words = p_words
                            q_norm = p_norm
                            break

        # «Similar a la Santal»: perfumes de acordes parecidos (antes que la recomendación genérica)
        parecidos = self.similares(q_norm, limite=max(limite - 1, 4), genero=genero)
        if parecidos:
            return parecidos

        # 3. Intenciones de recomendación abierta / catálogo general
        RECOMMEND_KEYWORDS = {"recomiendas", "recomiendame", "recomiendan", "recomienda", "recomendacion", "recomendaciones", "sugerencia", "sugerencias", "sugieres"}
        is_rec = any(w in q_norm for w in RECOMMEND_KEYWORDS) or bool(re.search(r'\bque\s+(?:perfumes?|fragancias?)?\s*(?:me\s+)?(?:recomiendas|recomiendame|recomienda|comprar|elegir|tienen|manejan)\b', q_norm))
        if is_rec and not self._familias_pedidas(q_norm):
            if not self.find_brand(q_norm):
                return self.get_recommendations(q_norm, limite=limite)

        # 4. Intenciones de catálogo con filtro de género inteligente (ej: 'cual es el top', 'top 10', 'mas vendidos')
        is_top_query = bool(re.search(r'\b(top|top10|top\s*10|mas\s+vendidos?|mas\s+populares?|mejores|bestsellers?)\b', q_norm))
        if is_top_query:
            all_top = self.get_top10()
            if any(g in q_norm for g in ["unisex", "para ambos", "compartir"]):
                top_unisex = [t for t in all_top if "unisex" in t.get("genero", "").lower()]
                lines = [f"{i+1}. **{t['nombre']}** ({t.get('categoria', '')}): ${t.get('precio', 0):,.0f} COP".replace(",", ".") for i, t in enumerate(top_unisex)]
                rendered = f"TOP DE PERFUMES UNISEX MÁS VENDIDOS EN ALTA DENSIDAD:\n" + "\n".join(lines)
                if top_unisex:
                    rendered += f"\n\nEl perfume unisex más vendido de nuestra tienda es **{top_unisex[0]['nombre']}** con un precio oficial de ${top_unisex[0].get('precio', 0):,.0f} COP.".replace(",", ".")
                return {"type": "top10", "data": top_unisex, "rendered": rendered}
            elif any(g in q_norm for g in ["hombre", "masculino", "caballero"]):
                top_h = [t for t in all_top if "masculino" in t.get("genero", "").lower()]
                lines = [f"{i+1}. **{t['nombre']}** ({t.get('categoria', '')}): ${t.get('precio', 0):,.0f} COP".replace(",", ".") for i, t in enumerate(top_h)]
                rendered = f"TOP DE PERFUMES MASCULINOS MÁS VENDIDOS EN ALTA DENSIDAD:\n" + "\n".join(lines)
                if top_h:
                    rendered += f"\n\nEl perfume masculino más vendido de nuestra tienda es **{top_h[0]['nombre']}** con un precio oficial de ${top_h[0].get('precio', 0):,.0f} COP.".replace(",", ".")
                return {"type": "top10", "data": top_h, "rendered": rendered}
            elif any(g in q_norm for g in ["mujer", "femenino", "dama"]):
                top_m = [t for t in all_top if "femenino" in t.get("genero", "").lower()]
                lines = [f"{i+1}. **{t['nombre']}** ({t.get('categoria', '')}): ${t.get('precio', 0):,.0f} COP".replace(",", ".") for i, t in enumerate(top_m)]
                rendered = f"TOP DE PERFUMES FEMENINOS MÁS VENDIDOS EN ALTA DENSIDAD:\n" + "\n".join(lines)
                if top_m:
                    rendered += f"\n\nEl perfume femenino más vendido de nuestra tienda es **{top_m[0]['nombre']}** con un precio oficial de ${top_m[0].get('precio', 0):,.0f} COP.".replace(",", ".")
                return {"type": "top10", "data": top_m, "rendered": rendered}
            else:
                return {"type": "top10", "data": all_top, "rendered": self.render_top10(all_top)}

        if any(term in q_norm for term in ["envase", "botella", "frasco"]):
            envases = self.get_envases()
            return {"type": "envases", "data": envases, "rendered": self.render_envases(envases)}

        if any(term in q_norm for term in ["kit", "promocion", "combo"]):
            kits = self.get_kits()
            return {"type": "kits", "data": kits, "rendered": self.render_kits(kits)}

        # 4. Resolver de Familias Olfativas y Notas (Cítrico, Dulce, Especias, Acuático, Amaderado, Floral)
        olfactory_match = self.match_olfactory_family(q_norm, limite=limite, genero=genero)
        if olfactory_match:
            return olfactory_match

        # 5. Detección de Marca (ej: Carolina Herrera, Bharara, Dior, Lacoste)
        brand_match = self.find_brand(q_norm)
        if brand_match and not any(w in q_norm for w in ["blanca", "red", "king", "soleil", "rose", "ice", "fire"]):
            brand_products = self.get_products_by_brand(brand_match)
            if brand_products:
                return {
                    "type": "brand_catalog",
                    "brand": brand_match,
                    "data": brand_products,
                    "rendered": self.render_brand_catalog(brand_match, brand_products)
                }

        # =====================================================================
        # CAPA 1: RESOLUCIÓN EXACTA Y FUZZY-STRING (rapidfuzz)
        # =====================================================================
        q_clean = " ".join(q_words) if q_words else q_norm
        if q_clean and HAS_RAPIDFUZZ and self._product_names_cache:
            candidatos = process.extract(
                q_clean,
                self._product_names_cache,
                scorer=fuzz.token_set_ratio,
                processor=rf_utils.default_process,
                limit=5
            )
            # token_set_ratio da 100 a «Light blue» y a «Light blue living stromboli» si el cliente escribe
            # «light blue»: entre los empatados gana el nombre más parecido a lo escrito
            # Si el cliente escribe un número («thank u next 2»), gana el nombre que lo trae («Thank u next 2.0»)
            numeros = set(re.findall(r'\d+', q_clean))
            con_numeros = lambda nombre: numeros <= set(re.findall(r'\d+', nombre))  # noqa: E731
            best_match = max(candidatos, key=lambda c: (c[1] >= 75 and con_numeros(c[0]), c[1],
                                                        fuzz.ratio(q_clean, rf_utils.default_process(c[0])))) if candidatos else None
            if best_match and best_match[1] >= 75.0:
                matched_name, score, idx = best_match
                matched_id = self._product_ids_cache[idx]
                record = self.get_product_by_id(matched_id)
                if record:
                    # Validar si el usuario especificó una variante o color que no coincide con el producto recuperado
                    COLOR_MODIFIERS = ["rosada", "rose", "blanca", "white", "black", "noir", "rouge", "red", "gold", "silver", "ice", "fire", "green", "blue"]
                    conflicting = False
                    for mod in COLOR_MODIFIERS:
                        if mod in q_clean.lower() and mod not in record["nombre_norm"]:
                            conflicting = True
                            break

                    if not conflicting:
                        return {
                            "type": "product_card",
                            "data": record,
                            "rendered": self.render_product_card(record),
                            "score": score,
                            "source": "exact_fuzzy"
                        }
                    else:
                        brand_prods = self.get_products_by_brand(record["marca"])
                        if brand_prods:
                            return {
                                "type": "brand_catalog",
                                "brand": record["marca"],
                                "data": brand_prods,
                                "rendered": f"Actualmente no disponemos de la versión '{q_clean}' en tienda. Sin embargo, de la casa **{record['marca']}** tenemos disponibles las siguientes referencias oficiales:\n\n" +
                                            self.render_brand_catalog(record["marca"], brand_prods)
                            }

        # Coincidencia SQL clásica como respaldo de Capa 1
        if q_words:
            web_prods = self.find_products_by_sql(q_words)
            if len(web_prods) == 1:
                p = web_prods[0]
                return {"type": "product_card", "data": p, "rendered": self.render_product_card(p), "source": "sql_exact"}
            elif len(web_prods) > 1:
                return {"type": "multi_product", "data": web_prods, "rendered": self.render_multi_products(web_prods, q_clean), "source": "sql_multi"}

        # =====================================================================
        # CAPA 2: FALLBACK VECTORIAL SEMÁNTICO (Embeddings de descripciones)
        # =====================================================================
        if HAS_VECTORS and q_norm:
            vector_res = self.search_semantic_fallback(q_norm, top_k=2)
            if vector_res:
                if len(vector_res) == 1:
                    p = vector_res[0]
                    return {
                        "type": "product_card",
                        "data": p,
                        "rendered": self.render_product_card(p),
                        "source": "vector_fallback"
                    }
                else:
                    return {
                        "type": "multi_product",
                        "data": vector_res,
                        "rendered": self.render_multi_products(vector_res, "Recomendación Semántica"),
                        "source": "vector_fallback"
                    }

        return {"type": "none", "data": None, "rendered": None}

    # =========================================================================
    # MÉTODOS DE CONSULTA SQL
    # =========================================================================
    def get_product_by_id(self, prod_id: int) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM productos WHERE id = ?", (prod_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def find_classic_perfume(self, search_kw: str, q_words: list = None) -> dict:
        """Compatibilidad para consultar clásicos en la tabla unificada productos."""
        cur = self.conn.cursor()
        norm_kw = normalize_text(search_kw)
        cur.execute("SELECT * FROM productos WHERE nombre_norm LIKE ? OR marca_norm LIKE ? LIMIT 1",
                    (f"%{norm_kw}%", f"%{norm_kw}%"))
        row = cur.fetchone()
        if row:
            return dict(row)
        if q_words:
            placeholders = " AND ".join(["nombre_norm LIKE ?" for _ in q_words])
            params = [f"%{w}%" for w in q_words]
            cur.execute(f"SELECT * FROM productos WHERE {placeholders} LIMIT 1", params)
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def find_web_products(self, search_kw: str, q_words: list = None) -> list:
        """Compatibilidad para consultar productos en la tabla unificada productos."""
        cur = self.conn.cursor()
        norm_kw = normalize_text(search_kw)
        cur.execute("SELECT * FROM productos WHERE nombre_norm LIKE ? OR marca_norm LIKE ? LIMIT 6",
                    (f"%{norm_kw}%", f"%{norm_kw}%"))
        return [dict(r) for r in cur.fetchall()]

    def render_classic_card(self, c: dict) -> str:
        return self.render_product_card(c)


    def find_products_by_sql(self, q_words: list) -> list:
        cur = self.conn.cursor()
        placeholders = " AND ".join(["nombre_norm LIKE ?" for _ in q_words])
        params = [f"%{w}%" for w in q_words]
        cur.execute(f"SELECT * FROM productos WHERE {placeholders} LIMIT 6", params)
        rows = [dict(r) for r in cur.fetchall()]
        if rows:
            return rows

        placeholders_or = " OR ".join(["nombre_norm LIKE ?" for _ in q_words])
        cur.execute(f"SELECT * FROM productos WHERE {placeholders_or} LIMIT 4", params)
        return [dict(r) for r in cur.fetchall()]

    # Familias que el cliente puede pedir: (clave, palabras del cliente, acordes que la representan, título).
    # La última es una ocasión («para enamorar», «una cita»): se resuelve con acordes cálidos y envolventes.
    FAMILIAS = [
        ("citrico", ["citrico", "citricos", "citrica", "citricas", "limon", "limones", "bergamota", "mandarina", "naranja", "pomelo", "toronja"],
         ["citrico"], "Cítrico y Refrescante"),
        ("afrutado", ["afrutado", "afrutada", "afrutados", "afrutadas", "frutal", "frutales", "frutas", "frutos"],
         ["afrutado", "frutal gourmand", "tropical"], "Afrutado"),
        ("dulce", ["dulce", "dulces", "gourmand", "vainilla", "caramelo", "bombon", "malvavisco", "azucar", "miel", "chocolate"],
         ["dulce", "avainillado", "caramelo", "amielado", "frutal gourmand"], "Dulce y Gourmand"),
        ("especiado", ["especias", "especiado", "especiada", "especiados", "canela", "cardamomo", "pimienta", "clavo", "nuez moscada"],
         ["calido especiado", "fresco especiado", "especiado suave", "canela"], "Especiado Cálido"),
        ("amaderado", ["amaderado", "amaderada", "amaderados", "madera", "maderas", "cedro", "sandalo", "oud", "vetiver"],
         ["amaderado", "oud"], "Amaderado Elegante"),
        ("acuatico", ["acuatico", "acuatica", "marino", "marina", "marinos", "brisa marina", "fresco marino"],
         ["acuatico", "marino"], "Acuático y Marino"),
        ("floral", ["floral", "florales", "flores", "rosa", "rosas", "jazmin", "nardos", "orquidea", "lavanda"],
         ["floral", "floral blanco", "rosa", "nardos"], "Floral"),
        ("fresco", ["fresco", "frescos", "fresca", "frescas", "refrescante", "ligero", "ligera", "ligeros"],
         ["fresco", "fresco especiado", "citrico", "acuatico", "verde", "marino"], "Fresco"),
        ("seductor", ["enamorar", "enamorarla", "enamorarlo", "seducir", "seductor", "seductora", "conquistar", "cita", "citas",
                      "romantico", "romantica", "sensual"],
         ["avainillado", "ambar", "calido especiado", "dulce", "amaderado"], "Cálido y Seductor"),
    ]
    # Colores que no son familia: «lacoste rosada» no pide perfumes florales
    NO_FAMILIA = {"rosada", "rosado", "rosadas", "rosados"}

    def _familias_pedidas(self, q_norm: str) -> list:
        palabras = [w for w in q_norm.split() if w not in self.NO_FAMILIA]
        texto = " ".join(palabras)

        def menciona(t):
            # Palabra exacta o, en las largas, su raíz con cualquier final: «citricosito», «dulcecito», «maderita»
            if len(t) >= 5 and " " not in t:
                return re.search(r'\b' + re.escape(t[:-1]) + r'\w*', texto)
            return re.search(r'\b' + re.escape(t) + r'\b', texto)

        return [f for f in self.FAMILIAS if any(menciona(t) for t in f[1])]

    @staticmethod
    def _acordes(p: dict) -> list:
        """Acordes del perfume en orden de intensidad (el primero es el dominante)."""
        m = re.search(r'Acordes: ([^.]*)\.', p.get("descripcion_olfativa") or "")
        return [normalize_text(a) for a in m.group(1).split(",")] if m else []

    def _fuerza(self, p: dict, familia) -> float:
        """Cuánto pesa una familia en el perfume: 6 si es el acorde dominante, 1 si es el sexto; 0,5 si solo aparece en notas."""
        acordes = self._acordes(p)
        posiciones = [i for i, a in enumerate(acordes) if any(a == t or a.startswith(t) for t in familia[2])]
        if posiciones:
            return 6 - min(posiciones)
        return 0.5 if any(re.search(r'\b' + re.escape(t) + r'\b', p.get("busqueda_norm") or "") for t in familia[1]) else 0

    def _todos_los_productos(self) -> list:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM productos")
        return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _orden_genero(p: dict, genero) -> int:
        g = (p.get("genero") or "").lower()
        if genero in ("Masculino", "Femenino"):
            return 0 if genero.lower() in g else 1
        return 0 if "unisex" in g else 1

    def match_olfactory_family(self, q_norm: str, limite: int = 4, genero=None) -> dict:
        """Perfumes de las familias pedidas, ordenados por cuánto pesa la familia en cada uno.

        Con varias familias («cítricos afrutados») van primero los que tienen todas. Género pedido + unisex,
        el pedido primero; sin género, primero los unisex (sirven para cualquiera).
        """
        familias = self._familias_pedidas(q_norm)
        if not familias:
            return None
        genero = genero or self.detectar_genero(q_norm)
        candidatos = []
        for p in self._todos_los_productos():
            if genero and not self._genero_compatible(p.get("genero"), genero):
                continue
            fuerzas = [self._fuerza(p, f) for f in familias]
            if max(fuerzas) < 1:
                continue
            todas = all(x >= 1 for x in fuerzas)
            candidatos.append((p["agotado"], not todas, self._orden_genero(p, genero), -sum(fuerzas),
                               p.get("top10") or 99, p["precio"], p))
        if not candidatos:
            return None
        prods = [c[-1] for c in sorted(candidatos, key=lambda c: c[:-1])[:limite]]
        display = " / ".join(f[3] for f in familias)
        lines = []
        for p in prods:
            precio_fmt = f"${p.get('precio', 0):,.0f} COP".replace(",", ".")
            lines.append(f"- **{p['nombre']}** ({p.get('marca', '')}): {precio_fmt} ({p.get('ml', '100ml')}) - {p.get('descripcion_olfativa', '')[:85]}...")
        rendered = (
            f"FRAGANCIAS CON PERFIL {display.upper()} EN ALTA DENSIDAD:\n" +
            "\n".join(lines) +
            f"\n\n¿Te gustaría conocer en detalle las notas olfativas o fijación de alguna de ellas?"
        )
        return {
            "type": "multi_product",
            "data": prods,
            "rendered": rendered,
            "source": "olfactory_" + "_".join(f[0] for f in familias)
        }

    # «Similar a la Santal», «parecido al Aventus», «algo como el Khamrah»
    PATRON_SIMILAR = re.compile(r'\b(similar\w*|parecid\w*|se parezca\w*|parecer\w*|estilo (?:de |del )?|tipo |como (?:el|la) )')

    def similares(self, q_norm: str, limite: int = 5, genero=None) -> dict:
        """Si el cliente pide algo parecido a un perfume del catálogo, los de acordes más cercanos (sin ese perfume)."""
        m = self.PATRON_SIMILAR.search(q_norm)
        if not m or not HAS_RAPIDFUZZ:
            return None
        resto = " ".join(w for w in q_norm[m.end():].split() if w not in STOPWORDS and len(w) > 1)
        if not resto:
            return None
        mejor = process.extractOne(resto, self._product_names_cache, scorer=fuzz.token_set_ratio,
                                   processor=rf_utils.default_process)
        if not mejor or mejor[1] < 75:
            return None
        ref = self.get_product_by_id(self._product_ids_cache[mejor[2]])
        if not ref:
            return None
        genero = genero or self.detectar_genero(q_norm)
        peso_ref = {a: 6 - i for i, a in enumerate(self._acordes(ref))}
        candidatos = []
        for p in self._todos_los_productos():
            if p["id"] == ref["id"] or (genero and not self._genero_compatible(p.get("genero"), genero)):
                continue
            parecido = sum(peso_ref[a] * (6 - i) for i, a in enumerate(self._acordes(p)) if a in peso_ref)
            if parecido:
                candidatos.append((p["agotado"], self._orden_genero(p, genero) if genero in ("Masculino", "Femenino") else 0,
                                   -parecido, p.get("top10") or 99, p))
        prods = [c[-1] for c in sorted(candidatos, key=lambda c: c[:-1])[:limite]]
        if not prods:
            return None
        # El perfume de referencia va al final del contexto: el modelo lo puede nombrar sin recomendarlo de primero
        return {"type": "similar", "data": prods + [ref], "referencia": ref["nombre"],
                "rendered": None, "source": "similares"}

    def find_brand(self, q_norm: str) -> str:
        for key, display in KNOWN_BRANDS:
            if re.search(r'\b' + re.escape(key) + r'\b', q_norm):
                return display
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT marca, marca_norm FROM productos")
        for r in sorted(cur.fetchall(), key=lambda r: -len(r["marca_norm"])):
            if len(r["marca_norm"]) > 2 and re.search(r'\b' + re.escape(r["marca_norm"]) + r'\b', q_norm):
                return r["marca"]
        return ""

    def get_products_by_brand(self, brand: str) -> list:
        cur = self.conn.cursor()
        norm_b = normalize_text(brand)
        cur.execute("SELECT * FROM productos WHERE marca_norm LIKE ? OR nombre_norm LIKE ? LIMIT 6",
                    (f"%{norm_b}%", f"%{norm_b}%"))
        return [dict(r) for r in cur.fetchall()]

    def find_tech_guide(self, q_words: list, q_norm: str) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM guias_tecnicas")
        guides = [dict(r) for r in cur.fetchall()]

        best_guide = None
        best_score = 0
        for g in guides:
            q_text = g["pregunta_norm"]
            a_text = normalize_text(g["respuesta"])
            u_tokens = set(w for w in q_text.split() if w not in STOPWORDS and len(w) > 2)

            score = sum(5 for w in q_words if w in u_tokens or any(w in ut for ut in u_tokens))
            score += sum(1 for w in q_words if w in a_text)
            if score > best_score and score >= 3:
                best_score = score
                best_guide = g

        return best_guide

    # =========================================================================
    # FALLBACK SEMÁNTICO (VECTORES -> SQLite ID)
    # =========================================================================
    def search_semantic_fallback(self, query: str, top_k: int = 2) -> list:
        """
        Vectoriza la consulta semántica con cosine similarity normalizada contra
        las descripciones olfativas y recupera los registros duros por ID desde SQLite.
        """
        self._load_cached_embeddings()
        if self._cached_embeddings is None or not self._cached_emb_ids:
            return []

        model = self._get_vector_model()
        if not model:
            return []

        try:
            q_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            norm_cached = self._cached_embeddings / (np.linalg.norm(self._cached_embeddings, axis=1, keepdims=True) + 1e-9)
            similarities = np.dot(norm_cached, q_emb.T).flatten()
            top_indices = np.argsort(similarities)[::-1][:top_k]

            results = []
            for idx in top_indices:
                if similarities[idx] > 0.25:  # Umbral mínimo de afinidad semántica
                    matched_id = self._cached_emb_ids[idx]
                    rec = self.get_product_by_id(matched_id)
                    if rec:
                        results.append(rec)
            return results
        except Exception as e:
            print(f"Error en fallback semántico: {e}")
            return []

    # =========================================================================
    # CATÁLOGO GENERAL (TOP 10, ENVASES, KITS)
    # =========================================================================
    def get_top10(self) -> list:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM top10 ORDER BY posicion ASC")
        return [dict(r) for r in cur.fetchall()]

    def get_envases(self) -> list:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM envases LIMIT 8")
        return [dict(r) for r in cur.fetchall()]

    def get_kits(self) -> list:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM kits LIMIT 6")
        return [dict(r) for r in cur.fetchall()]

    def get_recommendations(self, q_norm: str, limite: int = 4) -> dict:
        """Recomendación abierta con datos de SQLite: favoritos del Top 10 primero, filtrando por género si se pide."""
        cur = self.conn.cursor()
        # El género pedido va primero; los unisex solo completan la lista
        if any(g in q_norm for g in ["hombre", "masculino", "caballero"]):
            filtro, titulo, primero = "WHERE genero LIKE '%Masculino%' OR genero LIKE '%Unisex%'", "PERFUMES PARA HOMBRE RECOMENDADOS", "Masculino"
        elif any(g in q_norm for g in ["mujer", "femenino", "dama"]):
            filtro, titulo, primero = "WHERE genero LIKE '%Femenino%' OR genero LIKE '%Unisex%'", "PERFUMES PARA MUJER RECOMENDADOS", "Femenino"
        elif any(g in q_norm for g in ["unisex", "ambos", "compartir"]):
            filtro, titulo, primero = "WHERE genero LIKE '%Unisex%'", "PERFUMES UNISEX RECOMENDADOS", "Unisex"
        else:
            filtro, titulo, primero = "", "FRAGANCIAS FAVORITAS DE ALTA DENSIDAD", ""
        cur.execute(f"SELECT * FROM productos {filtro} ORDER BY agotado ASC, "
                    f"CASE WHEN ? <> '' AND genero LIKE ? THEN 0 ELSE 1 END, COALESCE(top10, 99) ASC, id ASC LIMIT ?",
                    (primero, f"%{primero}%", limite))
        prods = [dict(r) for r in cur.fetchall()]
        lines = [f"- **{p['nombre']}** ({p.get('marca', '')}): ${p.get('precio', 0):,.0f} COP ({p.get('ml', '100ml')})".replace(",", ".") for p in prods]
        rendered = f"{titulo}:\n" + "\n".join(lines) + f"\n\nTodas en Extrait de Parfum, con fijación de {DURACION_PIEL}."
        return {"type": "recommendation", "data": prods, "rendered": rendered}

    # =========================================================================
    # EXTRACTIVE RENDERING BLINDADO (DATOS DUROS DIRECTOS DESDE SQLITE)
    # =========================================================================
    def render_product_card(self, p: dict) -> str:
        """Renderiza una ficha de producto blindada directamente desde SQLite."""
        precio_fmt = f"${p.get('precio', 0):,.0f} COP".replace(",", ".")
        duracion = p.get("duracion_piel") or DURACION_PIEL
        return (
            f"FICHA TÉCNICA Y COMERCIAL (OFICIAL ALTA DENSIDAD):\n"
            f"- **Producto:** {p.get('nombre')}\n"
            f"- **Casa / Marca:** {p.get('marca', 'Alta Densidad')}\n"
            f"- **Categoría:** {p.get('categoria', 'Alta Perfumería')} | **Género:** {p.get('genero', 'Unisex')}\n"
            f"- **Precio Oficial:** {precio_fmt}\n"
            f"- **Presentación:** {p.get('ml', '100ml')} | **Envase:** {p.get('envase', 'Vidrio')}\n"
            f"- **Fijación Real en Piel:** {duracion}\n"
            f"- **Perfil Olfativo:** {p.get('descripcion_olfativa', '')}\n"
            f"- **Recomendación de Uso:** {p.get('uso_recomendado', 'Aplicar en puntos de pulso.')}"
        )

    def render_multi_products(self, products: list, search_kw: str) -> str:
        """Renderiza una lista de productos coincidentes con precios extraídos de SQLite."""
        lines = []
        for p in products[:6]:
            precio_fmt = f"${p.get('precio', 0):,.0f} COP".replace(",", ".")
            ml = p.get("ml", "100ml")
            lines.append(f"- **{p.get('nombre')}** ({p.get('marca', '')}): {precio_fmt} ({ml})")

        return (
            f"REFERENCIAS DISPONIBLES EN TIENDA ALTA DENSIDAD:\n" +
            "\n".join(lines) +
            f"\n(Todas en Extrait de Parfum, con fijación de 8 a 12 horas en piel)."
        )

    def render_brand_catalog(self, brand: str, products: list) -> str:
        """Renderiza catálogo de marca con precios exactos de SQLite."""
        lines = []
        for p in products[:6]:
            precio = p.get("precio")
            if precio:
                precio_fmt = f"${precio:,.0f} COP".replace(",", ".")
                lines.append(f"- **{p.get('nombre')}**: {precio_fmt} ({p.get('ml', '100ml')})")
            else:
                lines.append(f"- **{p.get('nombre')}**: {p.get('duracion_piel') or DURACION_PIEL}")

        return (
            f"CATÁLOGO DE LA CASA {brand.upper()} EN ALTA DENSIDAD:\n" +
            "\n".join(lines) +
            f"\n\n¿Buscas una opción femenina, masculina o alguna nota en particular?"
        )

    def render_tech_guide(self, g: dict) -> str:
        return f"GUÍA TÉCNICA DE FORMULACIÓN Y QUÍMICA:\n{g.get('respuesta')}"

    def render_top10(self, top10: list) -> str:
        lines = [f"{t['posicion']}. **{t['nombre']}** ({t.get('categoria', '')} - {t.get('genero', '')}): ${t.get('precio', 0):,.0f} COP".replace(",", ".") for t in top10]
        return "TOP 10 PERFUMES MÁS VENDIDOS EN TIENDA ALTA DENSIDAD:\n" + "\n".join(lines) + "\n\n¿Te gustaría conocer en detalle las notas olfativas o fijación de alguna de estas referencias?"

    def render_envases(self, envases: list) -> str:
        lines = [f"- **{e['nombre']}** ({e.get('material', 'Vidrio')}): {e.get('descripcion', '')[:75]}..." for e in envases]
        return "ENVASES DISPONIBLES EN TIENDA ALTA DENSIDAD:\n" + "\n".join(lines)

    def render_kits(self, kits: list) -> str:
        lines = [f"- **{k['nombre']}** (${k.get('precio', 0):,.0f} COP): {k.get('descripcion', '')}".replace(",", ".") for k in kits]
        return "KITS Y PROMOCIONES EN TIENDA ALTA DENSIDAD:\n" + "\n".join(lines)


if __name__ == "__main__":
    kb = KnowledgeBase()
    kb.build_from_sources()

    print("\n--- PRUEBA 1: CAPA EXACTA / FUZZY ('art of universe recomendacion') ---")
    res1 = kb.search("art of universe recomendacion")
    print("Tipo:", res1.get("type"), "| Fuente:", res1.get("source"))
    print(res1.get("rendered")[:150] + "...")

    print("\n--- PRUEBA 2: CAPA VECTORIAL FALLBACK ('algo dulce y fresco para verano') ---")
    res2 = kb.search("algo dulce y fresco para verano")
    print("Tipo:", res2.get("type"), "| Fuente:", res2.get("source"))
    print(res2.get("rendered")[:150] + "...")

    print("\n--- PRUEBA 3: MARCA CAROLINA HERRERA ---")
    res3 = kb.search("Carolina no es una fragancia es una marca")
    print(res3.get("rendered")[:150] + "...")
