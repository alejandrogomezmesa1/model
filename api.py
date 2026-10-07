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
from post_validator import verificar_productos


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

# Prompt de sistema: el MISMO con el que se entrena (dataset_aura/salida/sistema_aura.txt, generado
# desde aura_conocimiento.SISTEMA_AURA). Si cambia una política, se regenera el dataset y se reentrena.
BASE_SYSTEM = (BASE_DIR / "dataset_aura" / "salida" / "sistema_aura.txt").read_text(encoding="utf-8").strip()



def load_model_and_kb():
    kb = KnowledgeBase()
    cur = kb.conn.cursor()
    cur.execute("SELECT count(*) as count FROM productos")
    if cur.fetchone()["count"] == 0:
        kb.build_from_sources()
    STATE["catalogo"] = kb.catalogo_precios()
    STATE["kits"] = kb.nombres_kits()

    # AURA_MODELO elige la carpeta de models/ (sirve para comparar el modelo nuevo contra el anterior);
    # sin ella se usa el primero que exista de esta lista.
    candidatos = [os.environ["AURA_MODELO"]] if os.environ.get("AURA_MODELO") else [
        "aura_v2", "aura_v2_sft", "mi_modelo_perfumista_v1", "mi_modelo_sft"]
    model_id, model_display = "Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-0.5B-Instruct (Base HF Hub)"
    for nombre in candidatos:
        model_dir = resolve_path(nombre, is_dir=True)
        if model_dir and os.path.isfile(os.path.join(model_dir, "model.safetensors")):
            model_id, model_display = model_dir, nombre
            break

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
# Serializa el acceso al modelo (GPU) y a la conexión SQLite (no thread-safe)
INFERENCE_LOCK = threading.Lock()


def run_turn(user_text: str, history: list, last_product: Optional[str] = None, gen_kwargs: Optional[dict] = None):
    gen_kwargs = gen_kwargs or {}
    kb = STATE["kb"]
    model = STATE["model"]
    tokenizer = STATE["tokenizer"]
    device = STATE["device"]

    # Correcciones manuales guardadas con 'corregir:' tienen prioridad
    override = kb.check_override(user_text)
    if override:
        return override, "override", last_product

    # RAG: bloques «CATÁLOGO RELEVANTE / KITS / CREA TU PERFUME», igual que en el dataset de entrenamiento
    contexto, productos = kb.contexto(user_text, history)
    system_context = BASE_SYSTEM + ("\n\n" + contexto if contexto else "")
    if productos:
        last_product = productos[0]["nombre"]

    trimmed_history = history[-4:]
    current_messages = [{"role": "system", "content": system_context}] + trimmed_history + [{"role": "user", "content": user_text}]

    prompt_formatted = tokenizer.apply_chat_template(
        current_messages, tokenize=False, add_generation_prompt=True
    )

    inputs = tokenizer(prompt_formatted, return_tensors="pt").to(device)

    temperature = float(gen_kwargs.get("temperature", 0.3))
    top_p = float(gen_kwargs.get("top_p", 0.9))
    max_new_tokens = int(gen_kwargs.get("max_tokens", 350))

    with torch.no_grad():
        output_tokens = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
            top_p=top_p if temperature > 0 else None,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
        )

    input_len = inputs.input_ids.shape[1]
    response_tokens = output_tokens[0][input_len:]
    raw_response = tokenizer.decode(response_tokens, skip_special_tokens=True).strip()

    # Mismo control que el backend de la tienda: productos inexistentes fuera, precios oficiales, kits sin negrita
    response_text = verificar_productos(raw_response, STATE["catalogo"], STATE["kits"])
    if not response_text:
        response_text = ("Disculpa, no tengo esa información a la mano 🙏 Un asesor te ayuda por WhatsApp al "
                         "+57 304 647 7694. ¿Te recomiendo algún perfume mientras tanto?")

    return response_text, "rag" if contexto else "text", last_product


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
    temperature: Optional[float] = 0.3
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 350
    session_id: Optional[str] = None
    stream: Optional[bool] = False


class NativeChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    temperature: Optional[float] = 0.3
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 350


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
    bold_items = re.findall(r"\*\*([^*\n]{3,60})\*\*", response_text)
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
