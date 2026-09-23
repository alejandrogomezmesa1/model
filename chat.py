import sys
import os
import re
import json
import uuid
import datetime
import unicodedata
import torch
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer

# Configurar encoding UTF-8 en Windows para evitar errores cp1252
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Agregar src al path para importar knowledge_db y post_validator
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR))

try:
    from knowledge_db import KnowledgeBase, normalize_text
    from post_validator import validate_and_sanitize
except ImportError:
    from src.knowledge_db import KnowledgeBase, normalize_text
    from src.post_validator import validate_and_sanitize


def resolve_path(relative_path, is_dir=False):
    """Busca un archivo o carpeta en la raíz, en data/ o en models/, tanto desde raíz como desde src/."""
    candidates = [
        BASE_DIR / relative_path,
        BASE_DIR / "data" / relative_path,
        BASE_DIR / "models" / relative_path,
        BASE_DIR.parent / relative_path,
        BASE_DIR.parent / "data" / relative_path,
        BASE_DIR.parent / "models" / relative_path,
    ]
    for c in candidates:
        if is_dir and c.is_dir():
            return str(c.resolve())
        elif not is_dir and c.is_file():
            return str(c.resolve())
    return None


def main():
    # 1. Cargar Base de Conocimiento Híbrida (SQLite + RapidFuzz + Fallback Vectorial)
    print("Inicializando Base de Conocimiento Híbrida (SQLite + Fuzzy + Vectores)...")
    kb = KnowledgeBase()
    # Si la base de datos no tiene datos, construirla
    cur = kb.conn.cursor()
    cur.execute("SELECT count(*) as count FROM productos")
    if cur.fetchone()["count"] == 0:
        print("Indexando catálogo, guías y embeddings por primera vez...")
        kb.build_from_sources()

    # 2. Selección del modelo y hardware
    custom_model_dir = resolve_path("mi_modelo_perfumista_v1", is_dir=True)
    if custom_model_dir and os.path.isfile(os.path.join(custom_model_dir, "model.safetensors")):
        model_id = custom_model_dir
        model_display = "Modelo Soberano Perfumista v1 (Entrenado con SFT + DPO RL)"
    else:
        custom_sft_dir = resolve_path("mi_modelo_sft", is_dir=True)
        if custom_sft_dir and os.path.isfile(os.path.join(custom_sft_dir, "model.safetensors")):
            model_id = custom_sft_dir
            model_display = "Modelo Soberano SFT (Fase 1 LoRA Merged)"
        else:
            model_id = "Qwen/Qwen2.5-0.5B-Instruct"
            model_display = "Qwen/Qwen2.5-0.5B-Instruct (Base HF Hub)"

    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        gpu_name = torch.cuda.get_device_name(0)
        print(f"Dispositivo: GPU NVIDIA ({gpu_name}) con BFloat16 acelerado")
    else:
        device = "cpu"
        dtype = torch.float32
        print("Dispositivo: CPU")

    print(f"Cargando {model_display}...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=dtype,
    ).to(device)
    model.eval()
    model.config.use_cache = True

    # Estadísticas de catálogo
    cur.execute("SELECT count(*) as c FROM productos")
    total_prods = cur.fetchone()["c"]

    print("\n" + "=" * 68)
    print("      ASISTENTE DE PERFUMERIA Y FORMULACION DE FRAGANCIAS      ")
    print("=" * 68)
    print(f"Motor de Inferencia: {model_display}")
    print(f"Base de conocimiento: {total_prods} fragancias verificadas en SQLite + RapidFuzz + Vectores.")
    print("Escribe tu pregunta o perfume (ej: 'santal 33', 'Bharara Soleil', 'top 10', 'maceración').")
    print("Comandos: 'limpiar' (reiniciar chat) | 'salir' (terminar) | 'corregir: <texto>' (aprendizaje activo)\n")

    base_system = (
        "Eres un asistente experto en perfumería técnica y artesanal, con conocimiento "
        "profundo de composición olfativa, química de fragancias y procesos de "
        "elaboración. Tu base de conocimiento incluye el documento 'Glosario Técnico de Perfumería'; "
        "consúltalo como referencia autorizada antes de responder sobre pirámide olfativa, concentraciones, alcohol "
        "perfumístico o maceración.\n\n"
        "## Reglas de vocabulario y precisión técnica\n\n"
        "1. PIRÁMIDE OLFATIVA: siempre estructura cualquier fórmula, análisis o "
        "recomendación en las tres capas: notas de salida (0-30 min, moléculas "
        "ligeras y volátiles), notas de corazón (30 min-4h, cuerpo del perfume) y "
        "notas de fondo (varias horas, fijación y persistencia). Nunca mezcles "
        "ingredientes de capas distintas sin aclarar en qué capa actúa cada uno.\n\n"
        "2. CONCENTRACIONES: usa siempre los términos correctos y sus rangos "
        "orientativos de % de esencia:\n"
        "- Eau Fraîche (1-3%), Eau de Cologne/EDC (2-5%), Eau de Toilette/EDT (5-15%), Eau de Parfum/EDP (15-20%), Parfum/Extrait de Parfum (20-40%).\n"
        "Aclara que estos rangos son orientativos y que la concentración no es el "
        "único factor de calidad: la formulación importa igual o más.\n\n"
        "3. ALCOHOL PERFUMÍSTICO: distingue siempre entre alcohol etílico "
        "desnaturalizado (uso industrial/cosmético, no potable, regulado) y no "
        "desnaturalizado (grado 96°, potencialmente potable, sujeto a "
        "regulación fiscal/sanitaria). Cuando el usuario pregunte por "
        "formulación, recuerda usar alcohol de grado cosmético/perfumístico para "
        "minimizar el 'olor a alcohol' residual.\n\n"
        "4. MACERACIÓN Y ESTABILIZACIÓN: cuando expliques o diseñes un proceso de "
        "producción, incluye siempre la etapa de maceración/reposo (no la omitas "
        "como si el perfume estuviera 'listo' tras mezclar). Explica el "
        "fundamento cuando sea relevante:\n"
        "- Enlaces de hidrógeno entre moléculas aromáticas y el etanol, que ralentizan la evaporación y suavizan la transición entre notas.\n"
        "- Formación de bases de Schiff (reacción de aldehídos con aminas de materias primas naturales), que suaviza el filo de las notas de salida con el tiempo.\n"
        "- Diferencia entre maceración en frío (oscuridad, temperatura controlada, preserva volátiles) y procesos con calor (más rápidos pero con riesgo de degradar notas delicadas).\n"
        "- Tiempos de referencia: de 2 semanas (fórmulas simples) a varios meses (composiciones finas).\n\n"
        "5. TERMINOLOGÍA GENERAL: usa correctamente sillage, proyección, "
        "longevidad, acorde, familia olfativa, absoluto, concreto, aceite "
        "esencial, materia prima, concentrado, reformulación e IFRA (límites de "
        "seguridad de materiales). No confundas 'aceite esencial' (destilado) con 'absoluto' (extraído por solvente).\n\n"
        "## Estilo de respuesta\n\n"
        "- Responde con precisión técnica pero en lenguaje claro, como lo haría un "
        "perfumista o químico cosmético explicando a un colega de marca.\n"
        "- Si el usuario pide una fórmula, entrega SIEMPRE la estructura: notas de "
        "salida / corazón / fondo, % orientativo de concentración, tipo de base "
        "hidroalcohólica, y una nota sobre tiempo de maceración recomendado.\n"
        "- Si detectas que el usuario confunde términos (por ejemplo, 'EDP es más "
        "fuerte porque tiene más alcohol'), corrige con precisión, sin ser condescendiente.\n"
        "- Cuando falte información regulatoria específica (país, normativa local "
        "de alcohol o IFRA vigente), acláralo y sugiere verificar la fuente "
        "oficial más reciente en lugar de inventar cifras."
    )

    history = []
    session_id = str(uuid.uuid4())[:8]
    last_retrieved_product = None

    while True:
        try:
            user_text = input("Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n¡Hasta luego!")
            break

        if not user_text:
            continue

        if user_text.lower() in ["limpiar", "clear"]:
            history = []
            last_retrieved_product = None
            print("Historial de conversación reiniciado.\n")
            continue

        if user_text.lower() in ["salir", "exit", "quit"]:
            print("¡Hasta pronto!")
            break

        # =====================================================================
        # COMANDO 'corregir:': PERSISTENCIA REAL (OVERRIDES + REGISTRO DPO)
        # =====================================================================
        user_lower = user_text.lower().strip()
        if user_lower in ["corregir", "/corregir", "corregir:"]:
            print("\n[MODO APRENDIZAJE ACTIVO]")
            print("Para registrar una corrección, escribe:")
            print("  corregir: <la respuesta o dato que debería haber dado el modelo>")
            print("Ejemplo:")
            print("  corregir: Lacoste no tiene versión rosada en tienda, solo Lacoste Blanca ($65.000 COP) y Lacoste Red ($65.000 COP).\n")
            continue

        if user_lower.startswith("corregir:") or user_lower.startswith("corregir ") or user_lower.startswith("/corregir"):
            correccion = re.sub(r'^(corregir:?|\/corregir)\s*', '', user_text, flags=re.IGNORECASE).strip()
            if not correccion:
                print("\nPor favor especifica la corrección. Ejemplo: 'corregir: El precio es $65.000 COP'\n")
                continue

            if history:
                ultimo_user = history[-2]["content"] if len(history) >= 2 else (last_retrieved_product or "Consulta anterior")
                ultimo_asistente = history[-1]["content"] if len(history) >= 1 else ""

                # 1. Guardar como override inmediato en SQLite y overrides.json
                target_key = last_retrieved_product or ultimo_user
                kb.save_override(target_key, correccion, field="general")
                if ultimo_user != target_key:
                    kb.save_override(ultimo_user, correccion, field="query")

                # 2. Acumular en correcciones_activas.jsonl para reentrenamiento DPO por lotes
                corr_file = BASE_DIR / "data" / "correcciones_activas.jsonl"
                reg = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "prompt": ultimo_user,
                    "chosen": correccion,
                    "rejected": ultimo_asistente,
                    "target_product": target_key
                }
                with open(corr_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(reg, ensure_ascii=False) + "\n")

                print(f"\n[APRENDIZAJE ACTIVO & OVERRIDE INMEDIATO] ¡Corrección registrada con éxito!")
                print(f"- Clave objetivo: {target_key}")
                print(f"- Respuesta guardada (Chosen): {correccion}")
                print(f"- Descartada (Rejected): {ultimo_asistente[:80]}...")
                print(f"Guardada en 'data/overrides.json' y 'data/correcciones_activas.jsonl'.")
                print("Se aplicará de inmediato con prioridad 1 en cualquier futura consulta.\n")

                history[-1]["content"] = correccion
            else:
                print("\nNo hay ninguna respuesta previa en este chat para corregir.\n")
            continue

        # =====================================================================
        # MANEJO DE AFIRMACIONES Y SEGUIMIENTOS CONVERSACIONALES BREVES ("Si", "Ok")
        # =====================================================================
        user_norm = normalize_text(user_text)
        AFFIRMATIONS = {"si", "claro", "dale", "ok", "vale", "bueno", "por favor", "porfa", "yes", "sii", "si por favor"}
        if user_norm in AFFIRMATIONS and history:
            response_text = (
                "¡Con mucho gusto! Cuéntame cuál de las opciones te llama más la atención o si buscas "
                "una recomendación según la ocasión (diario, citas o eventos elegantes), "
                "y te asesoro con sus notas olfativas, envases y duración en piel."
            )
            print(f"\nModelo: {response_text}\n")
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response_text})
            continue

        # =====================================================================
        # BÚSQUEDA RAG EN BASE DE CONOCIMIENTO (SQLITE + RAPIDFUZZ + VECTORES)
        # =====================================================================
        search_result = kb.search(user_text, history)
        res_type = search_result.get("type", "none")
        rendered_output = search_result.get("rendered")
        retrieved_data = search_result.get("data")

        # Respuestas extractivas directas y blindadas desde SQLite (0% alucinación)
        if res_type in ["greeting", "override", "top10", "recommendation", "brand_catalog", "envases", "kits", "tech_guide", "multi_product"]:
            response_text = rendered_output
            if res_type == "brand_catalog":
                last_retrieved_product = search_result.get("brand")
        else:
            # Manejo de producto activo para overrides
            if res_type == "product_card" and isinstance(retrieved_data, dict):
                last_retrieved_product = retrieved_data.get("nombre")

            # Construir el prompt con la base de datos oficial
            if rendered_output:
                system_context = (
                    f"{base_system}\n\n"
                    f"[DATOS OFICIALES Y VERIFICADOS DE LA BASE DE DATOS]:\n"
                    f"{rendered_output}\n\n"
                    f"INSTRUCCIONES CLAVE:\n"
                    f"- Saluda o responde cordialmente al cliente con el estilo elegante, experto y cercano de Alta Densidad.\n"
                    f"- Asesora directamente sobre la consulta del cliente basándote estrictamente en los datos oficiales de arriba.\n"
                    f"- Menciona los precios, mililitros, envases y fijaciones exactamente como están en los datos oficiales, sin alterarlos.\n"
                    f"- Varia tu redacción y tus preguntas finales. Nunca repitas la misma pregunta de cierre que ya hiciste en turnos previos."
                )
            else:
                system_context = base_system

            # Inferencia generativa neuronal con los pesos W (SFT + DPO)
            trimmed_history = history[-4:]
            current_messages = [{"role": "system", "content": system_context}] + trimmed_history + [{"role": "user", "content": user_text}]

            prompt_formatted = tokenizer.apply_chat_template(
                current_messages,
                tokenize=False,
                add_generation_prompt=True
            )

            inputs = tokenizer(prompt_formatted, return_tensors="pt").to(device)

            with torch.no_grad():
                output_tokens = model.generate(
                    **inputs,
                    max_new_tokens=220,
                    do_sample=True,
                    temperature=0.4,
                    top_p=0.9,
                    repetition_penalty=1.18,
                    pad_token_id=tokenizer.eos_token_id
                )

            input_len = inputs.input_ids.shape[1]
            response_tokens = output_tokens[0][input_len:]
            raw_response = tokenizer.decode(response_tokens, skip_special_tokens=True).strip()

            # Post-Validación y Guardrails contra la base de datos
            response_text = validate_and_sanitize(raw_response, retrieved_data)
            if not response_text or len(response_text) < 15:
                response_text = rendered_output or raw_response

        print(f"\nModelo: {response_text}\n")

        # Guardar en memoria de sesión
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})

        # Registrar interacción en archivo persistente para aprendizaje activo
        try:
            log_file = BASE_DIR / "data" / "interacciones_chat.jsonl"
            log_entry = {
                "session_id": session_id,
                "timestamp": datetime.datetime.now().isoformat(),
                "user": user_text,
                "assistant": response_text,
                "res_type": res_type
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
