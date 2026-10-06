import json
import sys
from pathlib import Path
import httpx

BASE = "http://127.0.0.1:8000"
KEY_FILE = Path(__file__).resolve().parent / "data" / ".api_key"
KEY = KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""

print("=" * 65)
print("TEST DE SEGURIDAD Y CONTRATO: API PRIVADA ASISTENTE DE PERFUMERÍA")
print("=" * 65)

with httpx.Client(timeout=120) as c:
    # 1. Health check público
    h = c.get(f"{BASE}/health")
    print(f"\n[1] GET /health -> {h.status_code} {h.json().get('status')}")
    assert h.status_code == 200

    # 2. Intento de acceso sin API key a /chat (DEBE devolver 401)
    print("\n[2] POST /chat sin API Key...")
    r_unauth = c.post(f"{BASE}/chat", json={"message": "hola", "session_id": "test_unauth"})
    print(f"    Status: {r_unauth.status_code} (Esperado: 401)")
    assert r_unauth.status_code == 401, f"Fallo de seguridad: la API permitió acceso sin clave: {r_unauth.status_code}"
    print("    [PASS] Acceso sin API key bloqueado correctamente con 401.")

    # 3. Intento de acceso con API key inválida a /chat (DEBE devolver 401)
    print("\n[3] POST /chat con API Key inválida...")
    r_bad_key = c.post(
        f"{BASE}/chat",
        headers={"Authorization": "Bearer clave_falsa_123"},
        json={"message": "hola", "session_id": "test_bad_key"}
    )
    print(f"    Status: {r_bad_key.status_code} (Esperado: 401)")
    assert r_bad_key.status_code == 401
    print("    [PASS] Acceso con clave inválida bloqueado con 401.")

    # 4. Acceso con API key válida (Bearer token)
    print("\n[4] POST /chat con API Key válida (Bearer)...")
    headers = {"Authorization": f"Bearer {KEY}"}
    payload = {"message": "cuanto cuesta la bharara king", "session_id": "abc123"}
    r_auth = c.post(f"{BASE}/chat", headers=headers, json=payload)
    print(f"    Status: {r_auth.status_code}")
    data = r_auth.json()
    print("    Payload devuelto:", json.dumps(data, indent=2, ensure_ascii=False))

    assert r_auth.status_code == 200
    assert "response" in data
    assert data.get("session_id") == "abc123"
    assert data.get("res_type") == "text"
    print("    [PASS] Acceso autorizado exitoso con formato correcto.")

    # 5. Verificación de CORS: Sitio autorizado (ej: http://localhost:3000)
    print("\n[5] Preflight CORS desde sitio autorizado (http://localhost:3000)...")
    cors_auth = c.options(
        f"{BASE}/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type"
        }
    )
    allow_origin = cors_auth.headers.get("access-control-allow-origin")
    print(f"    Access-Control-Allow-Origin: {allow_origin}")
    assert allow_origin == "http://localhost:3000", f"Origen no permitido: {allow_origin}"
    print("    [PASS] Sitio autorizado aceptado por CORS.")

    # 6. Verificación de CORS: Sitio NO autorizado (ej: https://malicious-site.com)
    print("\n[6] Preflight CORS desde sitio NO autorizado (https://malicious-site.com)...")
    cors_unauth = c.options(
        f"{BASE}/chat",
        headers={
            "Origin": "https://malicious-site.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type"
        }
    )
    unauth_allow = cors_unauth.headers.get("access-control-allow-origin")
    print(f"    Access-Control-Allow-Origin: {unauth_allow} (Esperado: None)")
    assert unauth_allow is None, f"CORS permitió origen no autorizado: {unauth_allow}"
    print("    [PASS] Sitio no autorizado bloqueado por CORS.")

print("\n" + "=" * 65)
print("TODAS LAS VERIFICACIONES DE SEGURIDAD Y PRIVACIDAD SUPERADAS")
print("=" * 65)
