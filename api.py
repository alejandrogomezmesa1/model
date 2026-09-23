"""
API REST del Asistente de Perfumería "Alta Densidad" (IA Soberana local).

Expone el modelo entrenado (SFT + DPO) y la base de conocimiento RAG (SQLite +
RapidFuzz + vectores) detrás de una API protegida con API Key, compatible con el
formato de OpenAI Chat Completions.

Ejecución local:
    ./hf-locql/Scripts/python.exe -m uvicorn api:app --host 0.0.0.0 --port 8000

Exposición pública (túnel):
    cloudflared tunnel --url http://localhost:8000
"""

import os
import re
import sys
import time
import uuid
import json
import secrets
import datetime
import threading
import unicodedata
from pathlib import Path
from typing import List, Optional, Dict, Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Encoding UTF-8 en Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR))

from knowledge_db import KnowledgeBase, normalize_text
from post_validator import validate_and_sanitize


# =============================================================================
# API KEY (generada una sola vez, configurable vía PERFUMISTA_API_KEY)
# =============================================================================
def load_or_create_api_key() -> str:
    env_key = os.environ.get("PERFUMISTA_API_KEY", "").strip()
    if env_key:
        return env_key

    key_file = BASE_DIR / "data" / ".api_key"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key

    key = "pk-" + secrets.token_urlsafe(32)
    key_file.write_text(key, encoding="utf-8")
    return key


API_KEY = load_or_create_api_key()


def verify_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> str:
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_api_key:
        provided = x_api_key.strip()

    if not provided or not secrets.compare_digest(provided, API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida o ausente")
    return provided


# =============================================================================
# MODELO Y BASE DE CONOCIMIENTO (carga perezosa en el arranque)
# =============================================================================
def resolve_path(relative_path: str, is_dir: bool = False) -> Optional[str]:
    candidates = [
        BASE_DIR / relative_path,
        BASE_DIR / "data" / relative_path,
        BASE_DIR / "models" / relative_path,
    ]
    for c in candidates:
        if is_dir and c.is_dir():
            return str(c.resolve())
        elif not is_dir and c.is_file():
            return str(c.resolve())
    return None


STATE = {
    "kb": None,
    "model": None,
    "tokenizer": None,
    "device": "cpu",
    "dtype": torch.float32,
    "model_display": "",
    "sessions": {},  # session_id -> {"history": [...], "last_product": ...}
}

BASE_SYSTEM = (
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


def load_model_and_kb():
    kb = KnowledgeBase()
    cur = kb.conn.cursor()
    cur.execute("SELECT count(*) as count FROM productos")
    if cur.fetchone()["count"] == 0:
        kb.build_from_sources()

    custom_model_dir = resolve_path("mi_modelo_perfumista_v1", is_dir=True)
    if custom_model_dir and os.path.isfile(os.path.join(custom_model_dir, "model.safetensors")):
        model_id = custom_model_dir
        model_display = "Modelo Soberano Perfumista v1 (SFT + DPO RL)"
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
    else:
        device = "cpu"
        dtype = torch.float32

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype).to(device)
    model.eval()
    model.config.use_cache = True

    return kb, model, tokenizer, device, dtype, model_display


# =============================================================================
# MOTOR DE TURNO (RAG + GENERACIÓN), mismo flujo que chat.py
# =============================================================================
AFFIRMATIONS = {"si", "claro", "dale", "ok", "vale", "bueno", "por favor", "porfa", "yes", "sii", "si por favor"}
EXTRACTIVE_TYPES = {"greeting", "override", "top10", "recommendation", "brand_catalog", "envases", "kits", "tech_guide", "multi_product"}

# Serializa el acceso al modelo (GPU) y a la conexión SQLite (no thread-safe)
INFERENCE_LOCK = threading.Lock()


def run_turn(user_text: str, history: list, last_product: Optional[str] = None, gen_kwargs: Optional[dict] = None):
    gen_kwargs = gen_kwargs or {}
    kb = STATE["kb"]
    model = STATE["model"]
    tokenizer = STATE["tokenizer"]
    device = STATE["device"]

    # Afirmaciones / seguimientos breves
    user_norm = normalize_text(user_text)
    if user_norm in AFFIRMATIONS and history:
        response_text = (
            "¡Con mucho gusto! Cuéntame cuál de las opciones te llama más la atención o si buscas "
            "una recomendación según la ocasión (diario, citas o eventos elegantes), "
            "y te asesoro con sus notas olfativas, envases y duración en piel."
        )
        return response_text, "affirmation", last_product

    search_result = kb.search(user_text, history)
    res_type = search_result.get("type", "none")
    rendered_output = search_result.get("rendered")
    retrieved_data = search_result.get("data")

    if res_type in EXTRACTIVE_TYPES:
        response_text = rendered_output
        if res_type == "brand_catalog":
            last_product = search_result.get("brand")
        return response_text, res_type, last_product

    if res_type == "product_card" and isinstance(retrieved_data, dict):
        last_product = retrieved_data.get("nombre")

    if rendered_output:
        system_context = (
            f"{BASE_SYSTEM}\n\n"
            f"[DATOS OFICIALES Y VERIFICADOS DE LA BASE DE DATOS]:\n"
            f"{rendered_output}\n\n"
            f"INSTRUCCIONES CLAVE:\n"
            f"- Saluda o responde cordialmente al cliente con el estilo elegante, experto y cercano de Alta Densidad.\n"
            f"- Asesora directamente sobre la consulta del cliente basándote estrictamente en los datos oficiales de arriba.\n"
            f"- Menciona los precios, mililitros, envases y fijaciones exactamente como están en los datos oficiales, sin alterarlos.\n"
            f"- Varia tu redacción y tus preguntas finales. Nunca repitas la misma pregunta de cierre que ya hiciste en turnos previos."
        )
    else:
        system_context = BASE_SYSTEM

    trimmed_history = history[-4:]
    current_messages = [{"role": "system", "content": system_context}] + trimmed_history + [{"role": "user", "content": user_text}]

    prompt_formatted = tokenizer.apply_chat_template(
        current_messages, tokenize=False, add_generation_prompt=True
    )

    inputs = tokenizer(prompt_formatted, return_tensors="pt").to(device)

    temperature = float(gen_kwargs.get("temperature", 0.4))
    top_p = float(gen_kwargs.get("top_p", 0.9))
    max_new_tokens = int(gen_kwargs.get("max_tokens", 220))

    with torch.no_grad():
        output_tokens = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=1.18,
            pad_token_id=tokenizer.eos_token_id,
        )

    input_len = inputs.input_ids.shape[1]
    response_tokens = output_tokens[0][input_len:]
    raw_response = tokenizer.decode(response_tokens, skip_special_tokens=True).strip()

    response_text = validate_and_sanitize(raw_response, retrieved_data)
    if not response_text or len(response_text) < 15:
        response_text = rendered_output or raw_response

    return response_text, res_type, last_product


# =============================================================================
# FASTAPI
# =============================================================================
app = FastAPI(
    title="Alta Densidad Perfumista API",
    description="API local del asistente de alta perfumería (IA soberana, SFT + DPO + RAG).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    print("Cargando modelo y base de conocimiento...")
    kb, model, tokenizer, device, dtype, model_display = load_model_and_kb()
    STATE["kb"] = kb
    STATE["model"] = model
    STATE["tokenizer"] = tokenizer
    STATE["device"] = device
    STATE["dtype"] = dtype
    STATE["model_display"] = model_display
    print(f"Modelo cargado: {model_display} en {device}")
    print(f"API Key del servicio: {API_KEY}")
    print("Listo para recibir solicitudes.")


# --- Modelos de datos ---
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "alta-densidad-perfumista-v1"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.4
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 220
    session_id: Optional[str] = None
    stream: Optional[bool] = False


class NativeChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    temperature: Optional[float] = 0.4
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 220


# --- Endpoints ---
@app.get("/")
def root():
    return {
        "service": "Alta Densidad Perfumista API",
        "model": STATE["model_display"],
        "status": "online" if STATE["model"] else "loading",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": STATE["model_display"],
        "device": STATE["device"],
        "api_key_set": bool(API_KEY),
    }


def _get_or_create_session(session_id: Optional[str]) -> tuple:
    if not session_id:
        session_id = str(uuid.uuid4())
    sess = STATE["sessions"].get(session_id)
    if sess is None:
        sess = {"history": [], "last_product": None}
        STATE["sessions"][session_id] = sess
    return session_id, sess


def _run_and_record(session_id: str, sess: dict, user_text: str, gen_kwargs: dict) -> tuple:
    with INFERENCE_LOCK:
        response_text, res_type, last_product = run_turn(
            user_text, sess["history"], sess.get("last_product"), gen_kwargs
        )
    sess["history"].append({"role": "user", "content": user_text})
    sess["history"].append({"role": "assistant", "content": response_text})
    sess["last_product"] = last_product
    return response_text, res_type


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
def chat_completions(req: ChatCompletionRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages vacío")

    # Separar historial del último turno del usuario
    msgs = [m for m in req.messages if m.role in ("user", "assistant")]
    if not msgs or msgs[-1].role != "user":
        raise HTTPException(status_code=400, detail="El último mensaje debe ser del usuario")

    user_text = msgs[-1].content
    prior = [{"role": m.role, "content": m.content} for m in msgs[:-1]]

    session_id = req.session_id or str(uuid.uuid4())
    sess = STATE["sessions"].get(session_id)
    if sess is None:
        sess = {"history": prior, "last_product": None}
        STATE["sessions"][session_id] = sess
    else:
        sess["history"] = (sess["history"] + prior)[-40:]

    gen_kwargs = {"temperature": req.temperature, "top_p": req.top_p, "max_tokens": req.max_tokens}
    response_text, res_type = _run_and_record(session_id, sess, user_text, gen_kwargs)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or "alta-densidad-perfumista-v1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/chat", dependencies=[Depends(verify_api_key)])
def native_chat(req: NativeChatRequest):
    session_id, sess = _get_or_create_session(req.session_id)
    gen_kwargs = {"temperature": req.temperature, "top_p": req.top_p, "max_tokens": req.max_tokens}
    response_text, res_type = _run_and_record(session_id, sess, req.message, gen_kwargs)
    return {
        "session_id": session_id,
        "response": response_text,
        "res_type": res_type,
    }


@app.delete("/session/{session_id}", dependencies=[Depends(verify_api_key)])
def reset_session(session_id: str):
    if session_id in STATE["sessions"]:
        del STATE["sessions"][session_id]
        return {"session_id": session_id, "status": "reset"}
    return {"session_id": session_id, "status": "not_found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000)
