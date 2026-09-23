# 🌸 Asistente de Alta Perfumería y Formulación de Fragancias (IA Soberana)

Sistema de inteligencia artificial especializado en el dominio de la **alta perfumería**, **química de fragancias** y **formulación artesanal de laboratorio**, entrenado y ejecutado **100% en local** sobre hardware de consumo con aceleración GPU NVIDIA.

---

## 📑 Tabla de Contenidos
1. [¿Qué es este proyecto y para qué sirve?](#1-qué-es-este-proyecto-y-para-qué-sirve)
2. [Conceptos Fundamentales de Inteligencia Artificial](#2-conceptos-fundamentales-de-inteligencia-artificial)
3. [Arquitectura de Hardware y Optimización VRAM](#3-arquitectura-de-hardware-y-optimización-vram)
4. [Estructura del Proyecto](#4-estructura-del-proyecto)
5. [Bases de Datos y Conocimiento](#5-bases-de-datos-y-conocimiento)
6. [Pipeline de Entrenamiento: SFT + DPO (Aprendizaje por Refuerzo)](#6-pipeline-de-entrenamiento-sft--dpo-aprendizaje-por-refuerzo)
7. [Guía de Uso: Asistente Interactivo en Terminal](#7-guía-de-uso-asistente-interactivo-en-terminal)
8. [Hoja de Ruta y Próximos Pasos](#8-hoja-de-ruta-y-próximos-pasos)

---

## 1. ¿Qué es este proyecto y para qué sirve?

Este proyecto crea un modelo de lenguaje propio y soberano que actúa como **maestro perfumista consultor y formulador químico**, capaz de:
- **Identificar y desglosar perfumes comerciales de alta gama**: Pirámide olfativa completa (notas de salida, corazón y fondo), perfumista, casa matriz, año de lanzamiento, duración y estela.
- **Asesorar en formulación de laboratorio**: Proporciones de concentración (Splashes, EDC, EDT, EDP y Extraits), cálculos volumétricos de alcohol etílico desodorizado 96° y agua desmineralizada.
- **Química de fijadores y estabilización**: Uso de moléculas sintéticas clave (*Ambroxan, Iso E Super, Hedione, Galaxolide*) y prevención de problemas físico-químicos como el enturbiamiento (*efecto Ouzo o louching*).
- **Proceso de maceración y filtración**: Parámetros de maduración, reposo de 3 a 6 semanas a 15°C–18°C y decantación en frío a 0°C–4°C.
- **Privacidad y Soberanía Total**: No depende de APIs de terceros (OpenAI, Anthropic, etc.), no requiere internet tras la descarga inicial y opera completamente dentro de tu equipo.

---

## 2. Conceptos Fundamentales de Inteligencia Artificial

### A. LLM (*Large Language Model* / Modelo de Lenguaje)
Un modelo autoregresivo basado en la arquitectura *Transformer*. Su función matemática es predecir la distribución de probabilidad del siguiente *token* $P(w_t \mid w_{1}, \dots, w_{t-1})$.
En este proyecto utilizamos la familia **Qwen 2.5 (500M)**, un modelo compacto pero con una densidad de conocimiento y capacidad de seguimiento de instrucciones en español excepcional.

### B. Fine-Tuning Supervisado (SFT)
El modelo base original posee conocimientos generales de internet. El **SFT (Supervised Fine-Tuning)** ajusta los pesos neuronales presentándole cientos de pares pregunta-respuesta redactados con rigor técnico de perfumería para que adopte el vocabulario, estructura y tono de un maestro perfumista.

### C. LoRA (*Low-Rank Adaptation* / PEFT)
Entrenar un modelo de millones de parámetros completo sobrecargaría la memoria VRAM y borraría conocimientos generales (*catastrophic forgetting*). Con **LoRA**:
1. Los pesos originales $W_0$ quedan congelados (*frozen*).
2. Se inyectan dos matrices de bajo rango $A$ y $B$ en las capas de atención proyectada, tal que $\Delta W = B \cdot A$, donde $r \ll d$.
3. Solo se optimiza aproximadamente el **0.5% al 1%** de los parámetros, permitiendo entrenar en laptops en pocos minutos.

### D. DPO (*Direct Preference Optimization* / Aprendizaje por Refuerzo)
A diferencia del RLHF tradicional (que requiere entrenar un modelo de recompensa separado y luego usar algoritmos complejos e inestables como PPO), **DPO** optimiza directamente la política del modelo mediante una función de pérdida matemática implícita:
$$\mathcal{L}_{\text{DPO}}(\theta) = -\mathbb{E}_{(x, y_w, y_l)} \left[ \log \sigma \left( \beta \log \frac{\pi_\theta(y_w \mid x)}{\pi_{\text{ref}}(y_w \mid x)} - \beta \log \frac{\pi_\theta(y_l \mid x)}{\pi_{\text{ref}}(y_l \mid x)} \right) \right]$$
- $y_w$ (*chosen*): Respuesta experta, con química real y medidas precisas.
- $y_l$ (*rejected*): Respuesta con alucinaciones comunes (recetas de cocina como leche de coco, cebolla o aceite de oliva).
- $\beta = 0.1$: Factor de penalización que evita que el modelo se aleje excesivamente de su base lingüística.

### E. RAG (*Retrieval-Augmented Generation*)
Un modelo de 500M de parámetros **no debe memorizar una base de datos tabular en sus pesos** porque las capacidades paramétricas pequeñas provocan cruces de datos (*interferencias de tokens*).  
La arquitectura moderna desacopla ambas funciones:
- **El Modelo LLM (Memoria Procedimental)**: Aporta el razonamiento, la redacción en español, la cortesía y la estructura.
- **El Retriever RAG (Memoria Factual)**: Busca en memoria RAM en 1 milisegundo los datos exactos del catálogo o la guía técnica y los inyecta en el contexto. El resultado es **cero alucinación**.

---

## 3. Arquitectura de Hardware y Optimización VRAM

El sistema fue diseñado a la medida para ejecutarse de forma óptima en:
- **GPU**: NVIDIA GeForce RTX 3050 Laptop GPU (4.0 GB VRAM dedicada).
- **Arquitectura**: Ampere (soporte nativo de tensores BFloat16).
- **Precisión Numérica**: `torch.bfloat16` (16 bits de punto flotante con rango dinámico equivalente a FP32).

### Presupuesto de Memoria VRAM:
| Componente | Memoria Asignada | Estado |
| :--- | :---: | :--- |
| **Pesos del Modelo (500M)** | ~0.98 GB | Cargados en VRAM (BFloat16) |
| **KV Cache + Context Window** | ~0.35 GB | Dinámico en inferencia |
| **PyTorch CUDA Context** | ~0.45 GB | Runtime de NVIDIA |
| **Margen Libre de Seguridad** | **~2.20 GB** | Previene errores de CUDA OOM |

---

## 4. Estructura del Proyecto

```text
c:\Users\aleja\Desktop\Proyectos\modelo\
│
├── data/                               # Bases de datos y datasets del proyecto
│   ├── dataset_perfumeria.csv          # Catálogo oficial de 110 perfumes y pirámides
│   ├── guias_tecnicas.json             # 12 guías maestras de formulación y química
│   ├── dataset_reasoning.json          # 238 diálogos para entrenamiento SFT
│   ├── dataset_dpo.json                # Pares de preferencia para refuerzo DPO
│   └── dataset.json                    # Dataset original inicial
│
├── src/                                # Código fuente modular del sistema
│   ├── chat.py                         # Motor de inferencia y chat interactivo (RAG + LLM)
│   ├── train_sft.py                    # Script de entrenamiento Fase 1: LoRA SFT
│   ├── train_dpo.py                    # Script de alineación Fase 2: DPO (RL)
│   ├── build_dataset_reasoning.py      # Generador del dataset de razonamiento
│   └── build_dataset_dpo.py            # Generador del dataset de preferencias DPO
│
├── models/                             # Modelos y pesos entrenados
│   ├── mi_modelo_perfumista_v1/        # MODELO SOBERANO FINAL (SFT + DPO fusionado)
│   │   ├── model.safetensors           # Pesos finales compilados (988 MB)
│   │   ├── config.json                 # Configuración de arquitectura
│   │   ├── tokenizer.json              # Vocabulario y tokenizador
│   │   └── chat_template.jinja         # Plantilla oficial de diálogo
│   └── mi_modelo_sft/                  # Checkpoint intermedio de Fase 1
│
├── checkpoints/                        # Checkpoints de entrenamiento
│   ├── sft/                            # Estados de la Fase 1
│   └── dpo/                            # Estados de la Fase 2
│
├── legacy/                             # Scripts y pruebas iniciales archivadas
│   ├── train.py                        # Script original monolítico
│   ├── model                           # Script inicial SmolLM
│   └── mi_modelo_final/                # Primer prototipo
│
├── chat.py                             # Launcher directo en la raíz
├── requirements.txt                    # Dependencias Python
├── .gitignore                          # Exclusiones de Git
└── hf-locql/                           # Entorno virtual Python con PyTorch CUDA
```

---

## 5. Bases de Datos y Conocimiento

### A. Catálogo Tabular (`data/dataset_perfumeria.csv`)
Contiene 110 referencias de 66 casas perfumistas (*Tom Ford, Creed, Le Labo, Dior, Chanel, Kilian, BDK, Parfums de Marly, Nishane, Roja Dove, etc.*).
- **Campos**: `nombre`, `marca`, `anio_lanzamiento`, `perfumista`, `genero`, `familia_olfativa`, `notas_salida`, `notas_corazon`, `notas_fondo`, `duracion`, `estela`.

### B. Guías Técnicas Maestras (`data/guias_tecnicas.json`)
Compendio de 12 guías químicas de laboratorio:
1. Proceso de maceración y etapas temporales.
2. Cálculos matemáticos y formulación de 100 ml de EDP al 18%.
3. Tabla comparativa de concentraciones (Splash vs EDC vs EDT vs EDP vs Parfum).
4. Moléculas fijadoras (*Ambroxan, Iso E Super, Hedione, Galaxolide, Resinas*).
5. Solución al enturbiamiento (*efecto Ouzo / louching*) por exceso de agua o terpenos.
6. Estructura y velocidad de evaporación de la pirámide olfativa.
7. Selección de alcohol etílico desodorizado a 96°.
8. Comportamiento cinético y química en piel según pH y lípidos.
9. Densidad y dilución en peso.
10. Protección contra radiación UV y oxidación (antioxidantes BHT / tocoferol).
11. Maduración del concentrado puro vs Maceración hidroalcohólica.
12. Acordes y notas gourmand.

---

## 6. Pipeline de Entrenamiento: SFT + DPO (Aprendizaje por Refuerzo)

Para reproducir o reentrenar el modelo con nuevos datos:

### Paso 1: Generar los datasets estructurados
```powershell
& ./hf-locql/Scripts/python.exe src/build_dataset_reasoning.py
& ./hf-locql/Scripts/python.exe src/build_dataset_dpo.py
```

### Paso 2: Fase 1 - Supervised Fine-Tuning (SFT)
Entrena la base con LoRA ($r=16, \alpha=16$, 3 épocas, $lr=10^{-4}$) y exporta los pesos fusionados a `models/mi_modelo_sft/`:
```powershell
& ./hf-locql/Scripts/python.exe src/train_sft.py
```

### Paso 3: Fase 2 - Direct Preference Optimization (DPO RL)
Alinea las preferencias mediante refuerzo con $\beta=0.1$ y $lr=5 \times 10^{-6}$, suprimiendo alucinaciones y exportando el modelo final a `models/mi_modelo_perfumista_v1/`:
```powershell
& ./hf-locql/Scripts/python.exe src/train_dpo.py
```

---

## 7. Guía de Uso: Asistente Interactivo en Terminal

Para interactuar con el modelo en cualquier momento, abre PowerShell en la raíz del proyecto y ejecuta:

```powershell
& ./hf-locql/Scripts/python.exe chat.py
```

### Ejemplos de consultas:
- **Consultar un perfume**:
  ```text
  Tú: santal 33
  Modelo: Le Labo Santal 33 (Casa: Le Labo, Año: 2011)
  - Perfumista: Frank Voelkl
  - Familia: Amaderado
  - Salida: Cardamomo, Iris, Violeta
  - Corazón: Cedro, Papyrus
  - Fondo: Sándalo, Cuero, Almizcle
  - Rendimiento: Duración Duradero, Estela Moderado a fuerte.
  ```

- **Consultar formulación y maceración**:
  ```text
  Tú: como debo macerar un perfume y cuanto tiempo
  Modelo: Explica las 4 fases de laboratorio (mezcla inicial 15-20%, maduración en frasco ámbar a 15-18°C, reposo de 3 a 6 semanas y decantación en frío a 0°C-4°C).
  ```

- **Recomendación por notas o marcas**:
  ```text
  Tú: perfumes de Tom Ford
  Tú: fragancias con notas de vainilla y tabaco
  ```

- **Comandos especiales**:
  - `limpiar`: Reinicia el historial de la conversación.
  - `salir`: Cierra la sesión de chat.

---

## 8. Hoja de Ruta y Próximos Pasos

1. **Interfaz Gráfica (GUI)**:
   - Crear una aplicación web local ligera y visualmente atractiva (HTML5 / Vanilla CSS / FastAPI o Gradio).
2. **Calculadora Estequiométrica**:
   - Módulo interactivo donde el usuario ingresa el volumen deseado (ej. 50 ml) y la concentración objetivo (ej. 20%), y el sistema calcula gramos exactos de aceite, alcohol y agua desmineralizada.
3. **Expansión de la Base de Datos**:
   - Ampliar `data/dataset_perfumeria.csv` a 500+ fragancias de nicho y de diseñador.
