import json
import sys
from pathlib import Path
import httpx

BASE = "http://127.0.0.1:8000"
KEY_FILE = Path(__file__).resolve().parent / "data" / ".api_key"
KEY = KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""

print("=" * 60)
print("TEST DE LA API — Asistente de Perfumería")
print("=" * 60)

with httpx.Client(timeout=120) as c:
    # 1. Salud
    h = c.get(f"{BASE}/health")
    print(f"\n[1] /health -> {h.status_code} {h.json()['status']} | modelo: {h.json()['model']}")

    # 2. Sin API key (debe dar 401)
    r401 = c.post(f"{BASE}/chat", json={"message": "hola"})
    print(f"[2] Sin API key -> {r401.status_code} (esperado 401)")

    # 3. Con API key
    headers = {"Authorization": f"Bearer {KEY}"}
    preguntas = [
        "top 10 perfumes",
        "cuanto cuesta la bharara king",
        "que perfumes me recomiendas para hombre",
    ]
    for i, q in enumerate(preguntas, 3):
        r = c.post(f"{BASE}/chat", json={"message": q}, headers=headers)
        d = r.json()
        resp = d.get("response", d.get("detail", ""))
        print(f"\n[{i}] Tú: {q}")
        print(f"    Modelo: {resp[:300]}")

print("\n" + "=" * 60)
print("FIN DEL TEST")
