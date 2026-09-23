import json
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import torch
from datasets import Dataset, concatenate_datasets
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

# 1. Detección automática del mejor dispositivo
use_bf16 = False
use_fp16 = False
model_dtype = torch.float32

if torch.cuda.is_available():
    device = "cuda"
    if torch.cuda.is_bf16_supported():
        use_bf16 = True
        model_dtype = torch.bfloat16
        print("Hardware: GPU NVIDIA (CUDA) con soporte BFloat16")
    else:
        use_fp16 = True
        model_dtype = torch.float32
        print("Hardware: GPU NVIDIA (CUDA) con soporte FP16")
elif torch.backends.mps.is_available():
    device = "mps"
    model_dtype = torch.float32
    print("Hardware: Apple Silicon (MPS)")
else:
    device = "cpu"
    model_dtype = torch.float32
    print("Hardware: CPU (Modo estándar)")

# 2. Carga de Tokenizer y Modelo Base Instruct
model_id = "Qwen/Qwen2.5-0.5B-Instruct"
print(f"Cargando modelo base: {model_id}...")

tokenizer = AutoTokenizer.from_pretrained(model_id)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    dtype=model_dtype,
).to(device)

# 3. Cargar y procesar dataset_perfumeria.csv
csv_path = os.path.join(os.path.dirname(__file__), "dataset_perfumeria.csv")
print(f"Cargando dataset desde {csv_path}...")
df = pd.read_csv(csv_path)

csv_dialogs = []
for _, row in df.iterrows():
    # Diálogo 1: Consulta de ficha técnica y pirámide olfativa completa
    csv_dialogs.append({
        "messages": [
            {
                "role": "system",
                "content": "Eres un asistente experto en perfumería, química de fragancias y recomendación de perfumes. Responde en español de forma clara, precisa y profesional."
            },
            {
                "role": "user",
                "content": f"¿Cuáles son las notas y características del perfume {row['nombre']}?"
            },
            {
                "role": "assistant",
                "content": (
                    f"**{row['nombre']}** ({row['marca']}, {row['anio_lanzamiento']})\n"
                    f"- **Perfumista:** {row['perfumista']}\n"
                    f"- **Género:** {row['genero']} | **Familia olfativa:** {row['familia_olfativa']}\n"
                    f"- **Pirámide olfativa:**\n"
                    f"  - *Notas de salida:* {row['notas_salida']}\n"
                    f"  - *Notas de corazón:* {row['notas_corazon']}\n"
                    f"  - *Notas de fondo:* {row['notas_fondo']}\n"
                    f"- **Rendimiento:** Duración {str(row['duracion']).lower()} y estela {str(row['estela']).lower()}."
                )
            }
        ]
    })

    # Diálogo 2: Consulta de recomendación por familia olfativa y estilo
    csv_dialogs.append({
        "messages": [
            {
                "role": "system",
                "content": "Eres un asistente experto en perfumería, química de fragancias y recomendación de perfumes. Responde en español de forma clara, precisa y profesional."
            },
            {
                "role": "user",
                "content": f"Recomiéndame un perfume {str(row['genero']).lower()} de la familia {str(row['familia_olfativa']).lower()}."
            },
            {
                "role": "assistant",
                "content": (
                    f"Una excelente recomendación es **{row['nombre']}** de la casa **{row['marca']}** "
                    f"(creado en {row['anio_lanzamiento']} por el perfumista {row['perfumista']}). "
                    f"Pertenece a la familia {str(row['familia_olfativa']).lower()}, abriendo con notas de {row['notas_salida']}, "
                    f"con un corazón de {row['notas_corazon']} y fondo persistente de {row['notas_fondo']}. "
                    f"Ofrece una duración {str(row['duracion']).lower()} y estela {str(row['estela']).lower()}."
                )
            }
        ]
    })

csv_dataset = Dataset.from_list(csv_dialogs)
print(f"Dataset de perfumes procesado: {len(csv_dataset)} diálogos generados desde {len(df)} perfumes.")

# Combinar con dataset.json local (preguntas técnicas de maceración, dilución y formulación)
dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
if os.path.exists(dataset_path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        local_data = json.load(f)
    local_dataset = Dataset.from_list(local_data)
    dataset = concatenate_datasets([local_dataset, csv_dataset])
    print(f"Dataset final combinado listo: {len(dataset)} ejemplos ({len(local_dataset)} formulación + {len(csv_dataset)} catálogo de perfumes).")
else:
    dataset = csv_dataset
    print(f"Dataset final listo: {len(dataset)} ejemplos de perfumes.")

# 4. Configurar LoRA (PEFT)
# Adapta las proyecciones de atención sin tocar los pesos base originales
peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]
)

# 5. Configurar hiperparámetros de entrenamiento (calibrados para RTX 3050 4GB)
training_args = SFTConfig(
    output_dir="./checkpoints_lora",
    max_length=320,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    num_train_epochs=4,
    learning_rate=2e-4,
    logging_steps=10,
    bf16=use_bf16,
    fp16=use_fp16,
    report_to="none",
    save_strategy="no"
)

# 6. Instanciar SFTTrainer y entrenar
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=training_args,
    peft_config=peft_config
)

print("\n--- Iniciando entrenamiento LoRA ---")
trainer.train()

# 7. Fusionar los pesos de LoRA en el modelo base y guardar
print("\nFusionando adaptadores LoRA en el modelo base...")
merged_model = trainer.model.merge_and_unload()

output_dir = "./mi_modelo_final"
merged_model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)
print(f"Modelo final listo y guardado en: {output_dir}")
