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
# API KEYS (permite múltiples llaves válidas, configurable vía .api_key o PERFUMISTA_API_KEY)
# =============================================================================
def load_valid_api_keys() -> set:
    keys = set()
    env_key = os.environ.get("PERFUMISTA_API_KEY", "").strip()
    if env_key:
        keys.add(env_key)

    key_file = BASE_DIR / "data" / ".api_key"
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                keys.add(line)

    if not keys:
        key = "pk-" + secrets.token_urlsafe(32)
        key_file.write_text(key, encoding="utf-8")
        keys.add(key)
    return keys


def verify_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> str:
    provided = ""
    if authorization:
        auth_clean = authorization.strip()
        if auth_clean.lower().startswith("bearer "):
            provided = auth_clean[7:].strip()
        else:
            provided = auth_clean
    elif x_api_key:
        provided = x_api_key.strip()

    valid_keys = load_valid_api_keys()
    if not provided or not any(secrets.compare_digest(provided, k) for k in valid_keys):
        raise HTTPException(
            status_code=401,
            detail="Acceso no autorizado: API key inválida o ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
    "Eres AURA, la asesora olfativa virtual de 'Fragancias de Alta Densidad', una boutique de perfumería "
    "de lujo en Medellín, Colombia.\n\n"
    "Tu misión es asesorar a los clientes para que encuentren su perfume o kit ideal según su género, "
    "ocasión de uso (fiesta, oficina, cita romántica, diario) y gusto olfativo, con un tono elegante, "
    "experto, persuasivo y servicial (Dark Luxury).\n\n"
    "## Pilares Comerciales y Propuesta de Valor (Alta Densidad):\n"
    "1. CONCENTRACIÓN: 33% de concentración de esencia pura (Extracto de Perfume, muy superior al EDT o EDP convencional).\n"
    "2. DURACIÓN: Fijación garantizada en piel de 8 a más de 12 horas.\n"
    "3. FEROMONAS: Todas las fragancias contienen feromonas añadidas que intensifican la estela y la atracción.\n"
    "4. ENVASES: Frascos de vidrio de lujo (Cilindro tradicional, Swarosky, Cartier).\n"
    "5. ENVÍOS Y PAGOS: Envíos locales rápidos en Medellín (calle 77c # 91b - 74) y nacionales a toda Colombia. "
    "Pagos con Mercado Pago (tarjetas débito/crédito, PSE, Efecty, Nequi) y transferencias bancarias.\n"
    "6. ATENCIÓN HUMANA: Si un cliente tiene un reclamo o desea un pedido especial, derivarlo al WhatsApp: +57 304 647 7694.\n\n"
    "## Reglas Obligatorias de Interacción y Renderizado de Cards:\n"
    "1. Menciona SIEMPRE los nombres de las fragancias en negrita con su nombre exacto (ej: **ONE MILLON PACO RABANNE**, "
    "**THANK U NEXT 2.0 ARIANA GRANDE**, **BHARARA KING**, **SAUVAGE DIOR**), para que el frontend AURA renderice automáticamente "
    "su tarjeta interactiva con foto y botón '+ Añadir al carrito'.\n"
    "2. Indica los precios en Pesos Colombianos (COP) exactamente como constan en los datos oficiales de la tienda.\n\n"
    "## Conocimiento Técnico y de Laboratorio:\n"
    "Cuando el cliente consulte sobre formulación, maceración o química de fragancias, responde con rigor profesional:\n"
    "- PIRÁMIDE OLFATIVA: siempre en 3 capas (salida 0-30 min, corazón 30 min-4h, fondo varias horas persistentes).\n"
    "- ALCOHOL PERFUMÍSTICO: alcohol etílico desodorizado a 96° grado cosmético para evitar olor a alcohol residual.\n"
    "- MACERACIÓN: reposo de 3 a 6 semanas a 15-18°C y decantación en frío a 0-4°C."
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

def load_allowed_origins() -> List[str]:
    """Carga los orígenes permitidos (CORS).
    Prioridad:
      1. Variable de entorno ALLOWED_ORIGINS (ej: 'http://localhost:3000,https://midominio.com')
      2. Archivo data/allowed_origins.json
      3. Lista de desarrollo local por defecto
    """
    env_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if env_origins:
        return [o.strip() for o in env_origins.split(",") if o.strip()]

    origins_file = BASE_DIR / "data" / "allowed_origins.json"
    if origins_file.exists():
        try:
            data = json.loads(origins_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [str(o).strip() for o in data if str(o).strip()]
        except Exception as e:
            print(f"Advertencia al leer data/allowed_origins.json: {e}")

    default_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]
    try:
        origins_file.write_text(json.dumps(default_origins, indent=2), encoding="utf-8")
    except Exception:
        pass
    return default_origins


ALLOWED_ORIGINS = load_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    print(f"API Keys válidas: {len(load_valid_api_keys())} registradas en el sistema")
    print(f"Orígenes autorizados (CORS): {ALLOWED_ORIGINS}")
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


class NativeChatResponse(BaseModel):
    response: str
    session_id: str
    res_type: str = "text"
    products: Optional[List[str]] = Field(default_factory=list)


def extract_products_from_response(response_text: str, last_product: Optional[str] = None) -> List[str]:
    """Extrae los nombres exactos de productos para activar las Cards en AURA (Método B)."""
    found = []
    if last_product and isinstance(last_product, str) and last_product not in found:
        found.append(last_product)

    # Extraer nombres destacados en negrita (**NOMBRE**)
    bold_items = re.findall(r"\*\*([A-Za-z0-9\s\.\-]{3,50})\*\*", response_text)
    ignore_headers = {
        "producto", "precio", "casa", "marca", "presentacion", "envase", "perfil",
        "recomendacion", "genero", "categoria", "fijacion", "salida", "corazon",
        "fondo", "duracion", "rendimiento", "estela", "uso", "perfumista"
    }
    for item in bold_items:
        clean = item.strip().rstrip(":")
        if clean.lower() not in ignore_headers and len(clean) >= 4:
            if clean not in found:
                found.append(clean)

    return found[:6]


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
        "api_key_set": bool(load_valid_api_keys()),
    }


def _get_or_create_session(session_id: Optional[str]) -> tuple:
    if not session_id or not str(session_id).strip():
        session_id = str(uuid.uuid4())
    else:
        session_id = str(session_id).strip()
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


@app.post("/chat", response_model=NativeChatResponse, dependencies=[Depends(verify_api_key)])
def native_chat(req: NativeChatRequest):
    session_id, sess = _get_or_create_session(req.session_id)
    gen_kwargs = {"temperature": req.temperature, "top_p": req.top_p, "max_tokens": req.max_tokens}
    response_text, res_type = _run_and_record(session_id, sess, req.message, gen_kwargs)
    products = extract_products_from_response(response_text, sess.get("last_product"))
    return {
        "response": response_text,
        "session_id": session_id,
        "res_type": "text",
        "products": products,
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
