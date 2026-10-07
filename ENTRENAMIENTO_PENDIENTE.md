# Entrenar AURA con el dataset nuevo: estado

El dataset está en `dataset_aura/` de este repo (`generar_dataset.py`, `validar_dataset.py`, `evaluar.py` y la carpeta `salida/`).

Actualizado: 2026-10-07. Modelo: Qwen2.5-0.5B-Instruct con LoRA, SFT + DPO, RAG en SQLite y API FastAPI, en el PC con la RTX 3050 de 4 GB.

## Decisiones de negocio (tomadas el 2026-10-06)

| Tema | Decisión | Dónde quedó |
|---|---|---|
| Concentración «33 %» | **Confidencial.** AURA solo dice «Extrait de Parfum». | Regla 2 del prompt, pares DPO `filtra_concentracion`, validador y evaluación |
| Duración | **De 8 a 12 horas en piel.** | `SISTEMA_AURA`, respuestas de `aura_conocimiento.py`, generador, `politica_aura.md`, base de conocimiento |
| Formulación | **Cultura general sin cantidades:** puede explicar pirámide, maceración, fijadores, concentraciones, pero sin porcentajes, tiempos ni temperaturas. | Regla 7 del prompt, intención nueva `cultura_perfumeria` (`CULTURA` en `aura_conocimiento.py`), pares DPO `formula_cantidades`. Las guías técnicas con cantidades ya no se indexan en el RAG. |
| Efecty | **No se acepta.** | Respuesta a «¿reciben Efecty?», pares DPO `inventa_pago`, validador. Se quitó del prompt de la API. |

## Arreglos técnicos (hechos)

1. **Catálogo:** la base SQLite se construye desde `dataset_aura/salida/rag/conocimiento.json` (115 perfumes, 12 kits, envases y precios actuales de la tienda).
2. **Productos que no se venden:** se eliminaron los 110 «clásicos de colección» de `dataset_perfumeria.csv` y las guías de formulación con cantidades.
3. **`max_length`:** 2048 en SFT y DPO (el ejemplo más largo tiene ~1940 tokens), con gradient checkpointing. El SFT calcula la pérdida solo sobre la respuesta.
4. **Un solo prompt:** `api.py` usa `dataset_aura/salida/sistema_aura.txt` y arma el contexto con las mismas filas `CATÁLOGO RELEVANTE / KITS / CREA TU PERFUME` del dataset (`KnowledgeBase.contexto`). Ya no hay respuestas extractivas que salten el modelo; las respuestas pasan por `verificar_productos`, igual que `verificarRespuesta` del backend.
5. **Formato DPO:** `src/preparar_datos_aura.py` convierte SFT + rojo + DPO al formato conversacional de TRL y comprueba que el prompt coincida con el de la API.
6. **Contexto RAG:** el 100 % de los ejemplos con perfumes trae su contexto.

## Entrenamiento (hecho)

- SFT: 1096 ejemplos, 2 épocas, ~25 min → `models/aura_v2_sft/` (pérdida final 0,48).
- DPO: 320 pares, 1 época, lr 5e-6 con pérdida SFT de anclaje, ~6 min → `models/aura_v2/`.
  - Un primer intento con lr 2e-5 y 2 épocas degradó el modelo (mezclaba idiomas); está documentado en `src/train_dpo.py`.
  - `DPOTrainerRecortado` calcula los logits solo desde el inicio de la respuesta: pasa de ~60-90 s a 8 s por paso en 4 GB, con pérdida idéntica (verificado).

## Evaluación (`evaluar.py`, 168 casos que no están en el entrenamiento)

Ambos modelos con la misma API nueva (mismo prompt y RAG):

| | `aura_v2` (nuevo) | `mi_modelo_perfumista_v1` (anterior) |
|---|---|---|
| Aprobados | **105/168 (62,5 %)** | 28/168 (16,7 %) |
| Violaciones de reglas (filtraciones, «original», cupones, tarjeta…) | **0** | 2 |
| Productos inexistentes | 0 | 0 |
| Recomendación | 14/18 | 0/18 |
| Producto | 17/18 | 5/18 |
| Logística | 16/28 | 2/28 |
| Confidencial | 8/14 | 1/14 |
| Ataques (rojo) | 15/24 | 6/24 |

Reportes: `dataset_aura/salida/eval/reporte_20261007_1339.json` (nuevo) y `reporte_20261007_1351.json` (anterior).

## Pendiente

- Decidir si se publica `aura_v2`. La API lo carga por defecto; para volver al anterior: `$env:AURA_MODELO="mi_modelo_perfumista_v1"`.
- Debilidades del modelo de 0,5B vistas en la evaluación: a veces responde un tema vecino (p. ej. responde «originales» a «envío gratis»), cede en algunos ataques de inyección y dijo que un perfume es apto para niños. Siguiente paso recomendado: más variaciones por intención (`--semilla` distinta y unir), más pares DPO para salud y ataques, o un modelo base más grande (1,5B cabe en 4 GB con LoRA).
- `chat.py` (chat de terminal) todavía usa su propio prompt y las respuestas extractivas antiguas.
