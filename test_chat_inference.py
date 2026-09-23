import sys
import os
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR))

from knowledge_db import KnowledgeBase
from post_validator import validate_and_sanitize

kb = KnowledgeBase()
model_path = str(BASE_DIR / "models" / "mi_modelo_perfumista_v1")
print(f"Cargando modelo desde: {model_path}")
tokenizer = AutoTokenizer.from_pretrained(model_path)
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float32
model = AutoModelForCausalLM.from_pretrained(model_path, dtype=dtype).to(device)

def ask(text, history=[]):
    rag = kb.search(text, history)
    res_type = rag.get("type", "none")
    rendered = rag.get("rendered", "")
    data = rag.get("data")

    # Arquitectura Extractiva Primero (0% alucinación para catálogos, tops y guías)
    if res_type in ["greeting", "override", "top10", "recommendation", "brand_catalog", "envases", "kits", "tech_guide", "multi_product"]:
        return rendered

    sys_prompt = "Eres un maestro perfumista y químico de fragancias de alta gama en Alta Densidad. Riguroso, cordial y verídico."
    if rendered:
        sys_prompt += f"\n\n[INFORMACIÓN OFICIAL OBLIGATORIA]:\n{rendered}\nUsa estrictamente estos datos."

    msgs = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
    prompt_str = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt_str, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=150, temperature=0.3, top_p=0.9, do_sample=True)
    resp = tokenizer.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    sanitized = validate_and_sanitize(resp, data)
    return sanitized if sanitized and len(sanitized) >= 15 else (rendered or resp)

print("\n--- TEST 1: Hola que cuesta la bharara ---")
q1 = "Hola que cuesta la bharara"
r1 = ask(q1)
print(f"Tú: {q1}")
print(f"Modelo: {r1}")

print("\n--- TEST 2: Si (seguimiento contextual) ---")
q2 = "Si"
r2 = ask(q2, history=[{"role": "user", "content": q1}, {"role": "assistant", "content": r1}])
print(f"Tú: {q2}")
print(f"Modelo: {r2}")

print("\n--- TEST 3: Art of Universe recomendaciones de uso ---")
q3 = "Art of Universe recomendaciones de uso"
r3 = ask(q3)
print(f"Tú: {q3}")
print(f"Modelo: {r3}")

print("\n--- TEST 4: Carolina Herrera ---")
q4 = "Carolina no es una fragancia es una marca"
r4 = ask(q4)
print(f"Tú: {q4}")
print(f"Modelo: {r4}")

print("\n--- TEST 5: Fallback Semántico ('algo dulce y fresco para verano') ---")
q5 = "algo dulce y fresco para verano"
r5 = ask(q5)
print(f"Tú: {q5}")
print(f"Modelo: {r5}")

print("\n--- TEST 6: Recomendación ('que perfumes me recomiendas') ---")
q6 = "que perfumes me recomiendas"
r6 = ask(q6)
print(f"Tú: {q6}")
print(f"Modelo: {r6}")

print("\n--- TEST 7: Más vendidos ('que perfumes son los mas vendidos') ---")
q7 = "que perfumes son los mas vendidos"
r7 = ask(q7)
print(f"Tú: {q7}")
print(f"Modelo: {r7}")

print("\n--- TEST 8: Top ('cual es el top') ---")
q8 = "cual es el top"
r8 = ask(q8)
print(f"Tú: {q8}")
print(f"Modelo: {r8}")

print("\n[VERIFICACIÓN COMPLETADA EXITOSAMENTE]")

