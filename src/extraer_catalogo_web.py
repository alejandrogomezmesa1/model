"""
Script para extraer y estructurar todos los productos del catálogo
desde la base de datos de la página web de perfumería (Alta Densidad / Railway).
"""

import json
import urllib.request
import csv
import re
import sys
from pathlib import Path

# Configurar stdout para evitar errores de encoding en terminales Windows cp1252
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE_URL = "https://altadensidadpage-production.up.railway.app/api"

WORD_FIXES = {
    "acompa\ufffda": "acompañar",
    "acu\ufffdtica": "acuática",
    "acu\ufffdtico": "acuático",
    "alegr\ufffda": "alegría",
    "alt\ufffdsima": "altísima",
    "an\ufffds": "anís",
    "aristocr\ufffdtico": "aristocrático",
    "arom\ufffdtica": "aromática",
    "arom\ufffdtico": "aromático",
    "ar\ufffdbica": "arábica",
    "asi\ufffdtica": "asiática",
    "aut\ufffdntica": "auténtica",
    "azafr\ufffdn": "azafrán",
    "a\ufffdos": "años",
    "bamb\ufffd": "bambú",
    "ba\ufffdadas": "bañadas",
    "bomb\ufffdn": "bombón",
    "caf\ufffd": "café",
    "car\ufffdcter": "carácter",
    "cipr\ufffds": "ciprés",
    "cl\ufffdsico": "clásico",
    "colecci\ufffdn": "colección",
    "combinaci\ufffdn": "combinación",
    "composici\ufffdn": "composición",
    "contempor\ufffdnea": "contemporánea",
    "contempor\ufffdneo": "contemporáneo",
    "coraz\ufffdn": "corazón",
    "c\ufffdlida": "cálida",
    "c\ufffdlidas": "cálidas",
    "c\ufffdlido": "cálido",
    "c\ufffdlidos": "cálidos",
    "c\ufffdtrica": "cítrica",
    "c\ufffdtricas": "cítricas",
    "c\ufffdtrico": "cítrico",
    "c\ufffdtricos": "cítricos",
    "c\ufffdctel": "cóctel",
    "declaraci\ufffdn": "declaración",
    "des\ufffdrticos": "desérticos",
    "dise\ufffdada": "diseñada",
    "dise\ufffdado": "diseñado",
    "dise\ufffdador": "diseñador",
    "Dise\ufffdador": "Diseñador",
    "distinci\ufffdn": "distinción",
    "duraci\ufffdn": "duración",
    "d\ufffda": "día",
    "d\ufffdas": "días",
    "emblem\ufffdticas": "emblemáticas",
    "energ\ufffdtica": "energética",
    "energ\ufffdtico": "energético",
    "energ\ufffda": "energía",
    "en\ufffdrgica": "enérgica",
    "ep\ufffdtome": "epítome",
    "evoluci\ufffdn": "evolución",
    "explosi\ufffdn": "explosión",
    "extra\ufffddo": "extraído",
    "ex\ufffdtica": "exótica",
    "ex\ufffdtico": "exótico",
    "fijaci\ufffdn": "fijación",
    "fr\ufffdo": "frío",
    "fr\ufffdos": "fríos",
    "f\ufffdrmula": "fórmula",
    "ic\ufffdnica": "icónica",
    "ic\ufffdnicos": "icónicos",
    "impresi\ufffdn": "impresión",
    "interpretaci\ufffdn": "interpretación",
    "introducci\ufffdn": "introducción",
    "jazm\ufffdn": "jazmín",
    "juguet\ufffdn": "juguetón",
    "j\ufffdvenes": "jóvenes",
    "lim\ufffdn": "limón",
    "l\ufffdnea": "línea",
    "l\ufffdquido": "líquido",
    "magn\ufffdtica": "magnética",
    "magn\ufffdtico": "magnético",
    "maracuy\ufffd": "maracuyá",
    "mediterr\ufffdnea": "mediterránea",
    "met\ufffdtlicas": "metálicas",
    "met\ufffdtlico": "metálico",
    "m\ufffds": "más",
    "m\ufffdsticas": "místicas",
    "opci\ufffdn": "opción",
    "orqu\ufffdea": "orquídea",
    "pachul\ufffd": "pachulí",
    "pasi\ufffdn": "pasión",
    "pasteler\ufffda": "pastelería",
    "perfecci\ufffdn": "perfección",
    "perfumer\ufffda": "perfumería",
    "pi\ufffda": "piña",
    "po\ufffdtico": "poético",
    "pralin\ufffd": "praliné",
    "proyecci\ufffdn": "proyección",
    "p\ufffdblico": "público",
    "reci\ufffdn": "recién",
    "rom\ufffdtica": "romántica",
    "rom\ufffdticas": "románticas",
    "rom\ufffdtico": "romántico",
    "r\ufffdfagas": "ráfagas",
    "seducci\ufffdn": "seducción",
    "sofisticaci\ufffdn": "sofisticación",
    "s\ufffdndalo": "sándalo",
    "s\ufffdmbolo": "símbolo",
    "tambi\ufffdn": "también",
    "t\ufffd": "té",
    "versi\ufffdn": "versión",
    "vers\ufffdtil": "versátil",
    "vers\ufffdtiles": "versátiles",
    "visi\ufffdn": "visión",
    "\ufffdmbar": "ámbar",
    "\ufffdrabe": "árabe",
    "\ufffdxito": "éxito",
    "\ufffdnica": "única",
    "Ros\ufffd": "Rosé"
}

def fix_encoding(text: str) -> str:
    """Corrige caracteres dañados de codificación en palabras específicas."""
    if not isinstance(text, str):
        return text
    
    # Reemplazo por palabras completas
    def replace_word(m):
        w = m.group(0)
        return WORD_FIXES.get(w, WORD_FIXES.get(w.lower(), w))

    # Buscar palabras con caracteres \ufffd o caracteres especiales
    cleaned = re.sub(r'[\w\ufffd]+', replace_word, text)
    # Limpieza final de cualquier \ufffd residual
    cleaned = cleaned.replace('\ufffd', '')
    return cleaned


def fetch_endpoint(endpoint: str):
    url = f"{BASE_URL}/{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "Antigravity/CatalogExtractor 1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8")
        data = json.loads(content)
        return data.get("data", [])

def main():
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    print("🔌 Conectando a la base de datos de la página web (Alta Densidad / Railway)...")
    
    # 1. Extraer Productos
    print("📦 Extrayendo productos del catálogo...")
    productos_raw = fetch_endpoint("productos")
    print(f"   -> {len(productos_raw)} productos extraídos.")

    productos_limpios = []
    for p in productos_raw:
        item = {
            "id": p.get("id"),
            "nombre": fix_encoding(p.get("name", "")).strip(),
            "categoria": fix_encoding(p.get("category", "")).strip(),
            "genero": fix_encoding(p.get("gender", "")).strip(),
            "precio": float(p.get("price") or 0),
            "rating": p.get("rating", 4),
            "descripcion": fix_encoding(p.get("description", "")).strip(),
            "tallas": p.get("sizes", []),
            "tipos_envase": p.get("bottleTypes", []),
            "imagen": p.get("image", ""),
            "activo": bool(p.get("activo", 1))
        }
        productos_limpios.append(item)

    # 2. Extraer Envases
    print("🧪 Extrayendo envases disponibles...")
    envases_raw = fetch_endpoint("envases")
    print(f"   -> {len(envases_raw)} envases extraídos.")

    envases_limpios = []
    for e in envases_raw:
        item = {
            "id": e.get("id"),
            "nombre": fix_encoding(e.get("name", "")).strip(),
            "material": fix_encoding(e.get("material", "Vidrio")).strip(),
            "descripcion": fix_encoding(e.get("description", "")).strip(),
            "precio": float(e.get("price") or 0),
            "tallas": e.get("sizes", []),
            "imagen": e.get("image", "")
        }
        envases_limpios.append(item)

    # 3. Extraer Kits
    print("🎁 Extrayendo kits y promociones...")
    kits_raw = fetch_endpoint("kits")
    print(f"   -> {len(kits_raw)} kits extraídos.")

    kits_limpios = []
    for k in kits_raw:
        item = {
            "id": k.get("id"),
            "nombre": fix_encoding(k.get("nombre", "")).strip(),
            "descripcion": fix_encoding(k.get("descripcion", "")).strip(),
            "precio": float(k.get("precio") or 0),
            "imagen": k.get("imagen", "")
        }
        kits_limpios.append(item)

    # 4. Extraer Top 10
    print("⭐ Extrayendo Top 10 perfumes más vendidos...")
    top10_raw = fetch_endpoint("top10")
    print(f"   -> {len(top10_raw)} productos en Top 10 extraídos.")

    top10_limpios = []
    for t in top10_raw:
        item = {
            "posicion": t.get("posicion"),
            "producto_id": t.get("producto_id"),
            "nombre": fix_encoding(t.get("nombre", "")).strip(),
            "categoria": fix_encoding(t.get("categoria", "")).strip(),
            "genero": fix_encoding(t.get("genero", "")).strip(),
            "precio": float(t.get("precio") or 0),
            "rating": t.get("rating", 5)
        }
        top10_limpios.append(item)

    # Guardar productos en JSON
    json_prod_path = data_dir / "catalogo_web_productos.json"
    with open(json_prod_path, "w", encoding="utf-8") as f:
        json.dump(productos_limpios, f, ensure_ascii=False, indent=2)
    print(f"💾 Guardado JSON de productos en: {json_prod_path}")

    # Guardar productos en CSV
    csv_prod_path = data_dir / "catalogo_web_productos.csv"
    with open(csv_prod_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "nombre", "categoria", "genero", "precio", "rating", "tallas", "tipos_envase", "descripcion", "imagen"])
        for p in productos_limpios:
            writer.writerow([
                p["id"],
                p["nombre"],
                p["categoria"],
                p["genero"],
                p["precio"],
                p["rating"],
                "; ".join(p["tallas"]),
                "; ".join(p["tipos_envase"]),
                p["descripcion"],
                p["imagen"]
            ])
    print(f"💾 Guardado CSV de productos en: {csv_prod_path}")

    # Guardar paquete completo
    catalogo_completo = {
        "metadata": {
            "fuente": "Base de datos Alta Densidad Perfumería (Railway / MySQL)",
            "url_origen": BASE_URL,
            "total_productos": len(productos_limpios),
            "total_envases": len(envases_limpios),
            "total_kits": len(kits_limpios),
            "total_top10": len(top10_limpios)
        },
        "productos": productos_limpios,
        "envases": envases_limpios,
        "kits": kits_limpios,
        "top10": top10_limpios
    }
    json_all_path = data_dir / "catalogo_web_completo.json"
    with open(json_all_path, "w", encoding="utf-8") as f:
        json.dump(catalogo_completo, f, ensure_ascii=False, indent=2)
    print(f"💾 Guardado catálogo completo en: {json_all_path}")

    print("\n✅ Extracción completada exitosamente.")

if __name__ == "__main__":
    main()
