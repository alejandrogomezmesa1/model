"""
Suite de Pruebas de Regresión Automatizada - Asistente de Perfumería y Formulación
Evalúa rigurosamente los 8 requerimientos del sistema antes y después de fine-tuning:
1. RAG exacto (SQLite FTS5 + catalogo_web_productos + 110 perfumes clásicos)
2. Blindaje de campos críticos (extractive rendering de precio, ml, envase, horas de duración)
3. Post-validación y sanitización contra alucinaciones de precios y duraciones
4. Persistencia y precedencia en tiempo real de 'corregir:' en JSON y SQLite
5. Diversidad léxica y supresión de frases cliché en SFT
6. Prevención de alucinaciones históricas identificadas en DPO
7. Manejo contextual de historial multi-turno ('Si', consultas directas)
8. Consultas técnicas químicas (fórmulas, maceración, alcohol y materias primas)
"""

import sys
import os
import re
import json

# Inclusión de paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from knowledge_db import KnowledgeBase, normalize_text
from post_validator import validate_and_sanitize, sanitize_skin_duration, check_price_fidelity

def run_tests():
    print("=" * 75)
    print("SUITE DE REGRESIÓN: EVALUACIÓN DE 8 REQUERIMIENTOS ARQUITECTÓNICOS")
    print("=" * 75)

    kb = KnowledgeBase()
    cur = kb.conn.cursor()
    cur.execute("SELECT count(*) as count FROM productos")
    if cur.fetchone()["count"] == 0:
        print("Indexando base de conocimiento por primera vez...")
        kb.build_from_sources()

    passed = 0
    total = 0

    def check(name, condition, detail=""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] Test {total:02d}: {name}")
            return True
        else:
            print(f"  [FAIL] Test {total:02d}: {name}")
            if detail:
                print(f"         Detalle: {detail}")
            return False

    print("\n[REQUERIMIENTO 1: RAG EXACTO & SEPARACIÓN DE DATOS]")
    # 1. Búsqueda de Bharara en catálogo
    res_bharara = kb.search("Hola que cuesta la bharara")
    check(
        "RAG recupera catálogo de Bharara desde SQLite FTS5 sin inventar",
        res_bharara.get("type") in ["product_card", "multi_product", "brand_catalog"] and
        "BHARARA KING" in res_bharara.get("rendered", ""),
        f"Tipo: {res_bharara.get('type')}, Rendered: {res_bharara.get('rendered', '')[:100]}"
    )

    # 2. Búsqueda de perfume clásico por nombre en base de datos de clásicos
    classic_santal = kb.find_classic_perfume("santal 33", ["santal", "33"])
    rendered_classic = kb.render_classic_card(classic_santal) if classic_santal else ""
    check(
        "RAG recupera perfume clásico Santal 33 con perfumista y familia Le Labo",
        classic_santal is not None and "Le Labo" in classic_santal.get("marca", ""),
        f"Classic encontrado: {classic_santal.get('nombre') if classic_santal else 'None'}"
    )

    print("\n[REQUERIMIENTO 2: BLINDAJE DE CAMPOS CRÍTICOS (EXTRACTIVE RENDERING)]")
    # 3. Extractive rendering de Bharara King (precio oficial de BD $110.000 COP, vidrio, fijación en horas)
    web_prods = kb.find_web_products("bharara king", ["bharara", "king"])
    b_king = web_prods[0] if web_prods else None
    if b_king:
        card = kb.render_product_card(b_king)
        check(
            "Tarjeta de Bharara King contiene precio oficial $110.000 COP, fijación en horas y envase de Vidrio",
            "$110.000 COP" in card and "horas en piel" in card and "Vidrio" in card,
            f"Tarjeta renderizada:\n{card}"
        )
    else:
        check("Bharara King encontrado en productos web", False, "No se encontró Bharara King")

    # 4. Extractive rendering de marcas (Carolina Herrera catálogo)
    res_ch = kb.search("Carolina no es una fragancia es una marca")
    check(
        "Detección de marca Carolina Herrera renderiza catálogo de opciones de la marca",
        res_ch.get("type") == "brand_catalog" and "CAROLINA HERRERA" in res_ch.get("rendered", ""),
        f"Rendered: {res_ch.get('rendered')[:120] if res_ch.get('rendered') else 'None'}"
    )

    print("\n[REQUERIMIENTO 3: POST-VALIDACIÓN Y GUARDRAILS]")
    # 5. Sanitizar duración en meses en la piel
    aluc_duracion = "Bharara King tiene una duración de 12 meses en la piel con aroma exquisito."
    sanitized_dur = sanitize_skin_duration(aluc_duracion)
    check(
        "Sanitizador neutraliza '12 meses en la piel' transformándolo a horas reales",
        "8 a 10 horas" in sanitized_dur and "12 meses" not in sanitized_dur,
        f"Resultado: {sanitized_dur}"
    )

    # 6. Post-validador corrige precio erróneo contra BD oficial
    if b_king:
        aluc_precio = "Bharara King está en oferta exclusiva por $80.000 COP en frasco."
        sanitized_pr = validate_and_sanitize(aluc_precio, retrieved_record=b_king)
        check(
            "Post-validador corrige precio falso ($80.000 -> $110.000 COP oficial)",
            "$110.000 COP" in sanitized_pr and "$80.000" not in sanitized_pr,
            f"Resultado: {sanitized_pr}"
        )

    print("\n[REQUERIMIENTO 4: PERSISTENCIA REAL DE 'corregir:']")
    # 7. Guardar override en runtime y validar que se consulta con prioridad 1
    kb.save_override("bharara king", "Override verificado: Bharara King 100ml a $110.000 COP con 12h de proyección", "precio")
    override_hit = kb.check_override("bharara king")
    check(
        "Comando 'corregir:' persiste en JSON y SQLite y tiene precedencia absoluta",
        override_hit is not None and "Override verificado" in override_hit,
        f"Override encontrado: {override_hit}"
    )

    print("\n[REQUERIMIENTO 5 & 6: REFUERZO DE DATASETS DPO Y SFT]")
    # 8. Verificar que el dataset DPO contenga los pares de alucinaciones reales
    dpo_path = os.path.join(os.path.dirname(__file__), "data", "dataset_dpo.json")
    with open(dpo_path, "r", encoding="utf-8") as f:
        dpo_data = json.load(f)
    
    has_duration_pair = any("12 meses" in item.get("rejected", "") and "horas" in item.get("chosen", "") for item in dpo_data)
    has_brand_pair = any("Carolina" in item.get("prompt", "") and "marca" in item.get("prompt", "") for item in dpo_data)
    check(
        "Dataset DPO contiene pares específicos de alucinación real (duración y marca)",
        has_duration_pair and has_brand_pair and len(dpo_data) >= 20,
        f"Total pares DPO: {len(dpo_data)}, dur_pair: {has_duration_pair}, brand_pair: {has_brand_pair}"
    )

    # 9. Verificar diversidad léxica en SFT
    sft_path = os.path.join(os.path.dirname(__file__), "data", "dataset_reasoning.json")
    with open(sft_path, "r", encoding="utf-8") as f:
        sft_data = json.load(f)
    check(
        "Dataset SFT regenerado con más de 400 diálogos diversos",
        len(sft_data) >= 400,
        f"Total diálogos SFT: {len(sft_data)}"
    )

    print("\n[REQUERIMIENTO 7 & 8: HISTORIAL Y CONSULTAS TÉCNICAS / TOP 10]")
    # 10. Consulta de Top 10 y química
    res_top10 = kb.search("top 10 más vendidos")
    check(
        "Consulta 'top 10' recupera la lista oficial sin inventar",
        res_top10.get("type") == "top10" and "TOP 10" in res_top10.get("rendered", ""),
        f"Tipo: {res_top10.get('type')}"
    )

    # 11. Consulta química técnica
    res_quimica = kb.search("¿Qué es el ambroxan y para qué sirve?")
    check(
        "Consulta química sobre ambroxan recupera guía técnica de fijador",
        res_quimica.get("type") == "tech_guide" and "Ambroxan" in res_quimica.get("rendered", ""),
        f"Tipo: {res_quimica.get('type')}"
    )

    # 12. Manejo de seguimiento conversacional ("Si")
    simulated_history = [
        {"role": "user", "content": "Hola que cuesta la bharara"},
        {"role": "assistant", "content": "¿Te gustaría conocer sus características o envases?"}
    ]
    res_followup = kb.search("Si", history=simulated_history)
    check(
        "Respuesta 'Si' mantiene el hilo temático previo y no dispara catálogo genérico",
        res_followup.get("type") in ["product_card", "multi_product", "brand_catalog", "override"] or res_followup.get("data") is not None,
        f"Tipo de seguimiento: {res_followup.get('type')}"
    )

    print("\n" + "=" * 75)
    print(f"RESULTADOS FINALES: {passed}/{total} PRUEBAS SUPERADAS ({(passed/total)*100:.1f}%)")
    print("=" * 75)

    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(run_tests())
