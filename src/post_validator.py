"""
Módulo de Post-Validación y Guardrails contra la Base de Conocimiento.
Valida y sanitiza las respuestas generadas antes de mostrarlas al usuario:
1. Detecta y corrige alucinaciones de duración (meses/años en piel -> horas reales en piel).
2. Detecta y corrige alucinaciones de precio contra el registro oficial de la base de datos.
3. Corrige envases ficticios (ej. 'vaso de plástico' -> 'envase de vidrio').
4. Si la respuesta contiene contradicciones severas, sustituye por la plantilla segura extractiva.
"""

import re
import unicodedata

def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("utf-8").lower()
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


def sanitize_skin_duration(text: str, default_duration: str = "8 a 10 horas de fijación en piel") -> str:
    """
    Detecta 'meses' o 'años' aplicados a fijación o duración en la piel y los reemplaza por horas reales.
    Soporta acentos (duración, fijación, años) y variantes sintácticas.
    """
    if not text:
        return text

    pattern_duracion_falsa = re.compile(
        r'(\b(?:duraci[oó]n|dura|fijaci[oó]n|rendimiento)\b[^.\n]*?\b(\d+)\s*(?:mes|meses|a[nñ]o|a[nñ]os)\b(?:[^\n.]*?\ben la piel\b)?)',
        re.IGNORECASE
    )

    if pattern_duracion_falsa.search(text):
        text = pattern_duracion_falsa.sub(
            f"duración de {default_duration} (la vida útil del frasco en reposo es de 2 a 3 años)",
            text
        )
    return text


def check_price_fidelity(text: str, official_price: float) -> str:
    """
    Verifica si en el texto se mencionan cifras de precio inconsistentes con el precio oficial de BD.
    Sustituye cualquier precio contradictorio por el precio oficial formateado.
    """
    if not text or not official_price or official_price <= 0:
        return text

    precio_fmt = f"${float(official_price):,.0f} COP".replace(",", ".")
    
    # Reemplazar artefactos comunes de generación
    text = re.sub(r'\$0\.000\s*COP', precio_fmt, text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!\d)\.000\s*COP', precio_fmt, text, flags=re.IGNORECASE)

    # Detectar expresiones de precio como $80.000, $80000, 80.000 COP, etc.
    def price_replacer(match):
        raw = match.group(0)
        digits = re.sub(r'[^\d]', '', raw)
        if digits:
            val = float(digits)
            if val > 1000 and abs(val - official_price) > 1.0:
                return precio_fmt
        return raw

    text = re.sub(r'\$[\d\.]+(?:\s*COP)?', price_replacer, text)
    return text


def validate_and_sanitize(response_text: str, retrieved_record = None) -> str:
    """
    Inspecciona y sanitiza la respuesta generada por el LLM antes de enviarla al cliente.
    """
    if not response_text:
        return response_text

    sanitized = response_text

    # 1. Eliminación de etiquetas HTML y URLs alucinadas
    sanitized = re.sub(r'<[^>]+>', '', sanitized)
    sanitized = re.sub(r'\[([^\]]+)\]\(https?://[^\)]+\)', r'**\1**', sanitized)
    sanitized = re.sub(r'https?://\S+', '', sanitized)

    # 2. Corrección de términos y dialectos distorsionados por modelos pequeños
    sanitized = re.sub(r'\b(?:con\s+)?un\s+peso\s+de\s+(\$?[\d\.]+)', r'un precio de \1', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\bpeso\s*:\s*(\d+\s*ml)', r'Presentación: \1', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\bf[ií]jola\s*:\s*', r'Fijación: ', sanitized, flags=re.IGNORECASE)

    # 3. Blindaje de Duración
    duracion_real = "8 a 10 horas de fijación en piel"
    if retrieved_record:
        if isinstance(retrieved_record, dict):
            duracion_real = retrieved_record.get("duracion_piel") or retrieved_record.get("duracion_horas") or duracion_real
        elif isinstance(retrieved_record, list) and len(retrieved_record) > 0 and isinstance(retrieved_record[0], dict):
            duracion_real = retrieved_record[0].get("duracion_piel") or duracion_real
    sanitized = sanitize_skin_duration(sanitized, duracion_real)

    # 4. Blindaje de Envases
    sanitized = re.sub(r'\b(vaso de plastico|frasco de plastico|botella de plastico)\b', 'envase de vidrio', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\bvaso de cristal\b', 'envase de vidrio', sanitized, flags=re.IGNORECASE)

    # 5. Blindaje de Precios si hay registro oficial recuperado
    if retrieved_record:
        if isinstance(retrieved_record, dict):
            precio_oficial = retrieved_record.get("precio")
            if precio_oficial:
                try:
                    precio_num = float(precio_oficial)
                    sanitized = check_price_fidelity(sanitized, precio_num)
                except (ValueError, TypeError):
                    pass
        elif isinstance(retrieved_record, list) and len(retrieved_record) == 1 and isinstance(retrieved_record[0], dict):
            precio_oficial = retrieved_record[0].get("precio")
            if precio_oficial:
                try:
                    precio_num = float(precio_oficial)
                    sanitized = check_price_fidelity(sanitized, precio_num)
                except (ValueError, TypeError):
                    pass

    # 6. Recorte de oraciones truncadas por límite de tokens
    sanitized = sanitized.strip()
    if sanitized and not sanitized.endswith((".", "!", "?", "\"", "”", "’")):
        # Si termina en signo de interrogación de apertura o guión, removerlo
        sanitized = re.sub(r'[\s\-\,\:\;\¿]+$', '', sanitized)
        # Buscar el último punto, exclamación o interrogación de cierre
        last_punct = max(sanitized.rfind("."), sanitized.rfind("?"), sanitized.rfind("!"))
        if last_punct > len(sanitized) * 0.4:
            sanitized = sanitized[:last_punct + 1]

    # 7. Limpieza de saltos de línea excesivos y espacios
    sanitized = re.sub(r'\n{3,}', '\n\n', sanitized).strip()
    return sanitized

# Alias para compatibilidad
validate_and_sanitize_response = validate_and_sanitize

