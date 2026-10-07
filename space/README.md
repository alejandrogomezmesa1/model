---
title: AURA API
emoji: 🌸
colorFrom: pink
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# AURA API

API de la asesora AURA de Fragancias de Alta Densidad (`api.py` del repo `alejandrogomezmesa1/model`).
Carga el modelo `mansamusa04/aura-v2` y construye la base de conocimiento al arrancar.

Secrets necesarios (Settings → Variables and secrets):

- `HF_TOKEN`: token de lectura con acceso al modelo privado `mansamusa04/aura-v2`.
- `PERFUMISTA_API_KEY`: llave que deben enviar los clientes (`Authorization: Bearer <llave>`).

Uso: `POST /v1/chat/completions` (formato OpenAI) o `POST /chat`.
