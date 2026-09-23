import json
import os
import sys
import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def main():
    # 1. Detección de hardware
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
    else:
        device = "cpu"
        model_dtype = torch.float32
        print("Hardware: CPU (Modo estándar)")

    # 2. Carga del Modelo Base y Tokenizador
    model_id = "Qwen/Qwen2.5-0.5B-Instruct"
    print(f"Cargando modelo base: {model_id}...")

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=model_dtype,
    ).to(device)

    # 3. Cargar dataset_reasoning.json
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(base_dir, "..")) if os.path.basename(base_dir) == "src" else base_dir

    candidate_datasets = [
        os.path.join(project_root, "data", "dataset_reasoning.json"),
        os.path.join(base_dir, "dataset_reasoning.json")
    ]
    dataset_path = next((p for p in candidate_datasets if os.path.exists(p)), candidate_datasets[0])
    print(f"Cargando dataset de razonamiento desde: {dataset_path}...")

    with open(dataset_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    dataset = Dataset.from_list(raw_data)
    print(f"Dataset cargado con éxito: {len(dataset)} diálogos de razonamiento y formulación.")

    # 4. Configurar LoRA con hiperparámetros estables (anti-olvido)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=16,            # alpha/r = 1.0 para mantener gradientes suaves y estables
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]
    )

    # 5. Configurar hiperparámetros de entrenamiento
    checkpoints_dir = os.path.join(project_root, "checkpoints", "sft")
    training_args = SFTConfig(
        output_dir=checkpoints_dir,
        max_length=512,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        num_train_epochs=3,       # 3 épocas para asimilar el dominio sin sobreajustar
        learning_rate=1e-4,       # Tasa suave para preservar el lenguaje base
        warmup_steps=10,
        weight_decay=0.01,
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

    print("\n--- Iniciando Fase 1: Entrenamiento Supervisado (SFT) ---")
    trainer.train()

    # 7. Fusionar y guardar modelo SFT
    print("\nFusionando adaptadores LoRA SFT en el modelo base...")
    merged_model = trainer.model.merge_and_unload()

    output_dir = os.path.join(project_root, "models", "mi_modelo_sft")
    os.makedirs(output_dir, exist_ok=True)
    merged_model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Modelo SFT completado y guardado en: {output_dir}")

if __name__ == "__main__":
    main()
