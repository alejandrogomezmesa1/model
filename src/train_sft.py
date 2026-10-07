"""
Fase 1 — SFT de AURA con LoRA sobre Qwen2.5-0.5B-Instruct.

Entrena con data/aura_sft.jsonl (generado por src/preparar_datos_aura.py): el mismo prompt de
sistema y el mismo bloque de contexto RAG que usa api.py en inferencia. La pérdida se calcula
solo sobre la respuesta de AURA (formato prompt/completion).

Salida: models/aura_v2_sft/ (pesos fusionados).
"""
import os
import sys
import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"


def main():
    # 1. Hardware y precisión
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    use_fp16 = torch.cuda.is_available() and not use_bf16
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_dtype = torch.bfloat16 if use_bf16 else torch.float32
    print(f"Hardware: {device} · {'bf16' if use_bf16 else 'fp16' if use_fp16 else 'fp32'}")

    # 2. Modelo base y tokenizador
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=model_dtype).to(device)

    # 3. Dataset (prompt/completion conversacional)
    dataset_path = os.path.join(PROJECT_ROOT, "data", "aura_sft.jsonl")
    if not os.path.exists(dataset_path):
        raise SystemExit("Falta data/aura_sft.jsonl: corre primero src/preparar_datos_aura.py")
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    print(f"Dataset SFT: {len(dataset)} ejemplos")

    # 4. LoRA sobre todas las proyecciones lineales (atención + MLP)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    # 5. Hiperparámetros. max_length=2048 cubre el ejemplo más largo (~1940 tokens: prompt de
    #    sistema + contexto RAG + respuesta) sin cortar; gradient checkpointing para caber en 4 GB.
    training_args = SFTConfig(
        output_dir=os.path.join(PROJECT_ROOT, "checkpoints", "aura_sft"),
        max_length=2048,
        completion_only_loss=True,
        gradient_checkpointing=True,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=2,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_steps=0.05,  # fracción del total de pasos
        weight_decay=0.01,
        logging_steps=10,
        bf16=use_bf16,
        fp16=use_fp16,
        report_to="none",
        save_strategy="epoch",
        save_total_limit=1,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=training_args,
        processing_class=tokenizer,
        peft_config=peft_config,
    )

    print("\n--- Fase 1: SFT de AURA ---")
    trainer.train()

    # 6. Fusionar y guardar
    merged_model = trainer.model.merge_and_unload()
    output_dir = os.path.join(PROJECT_ROOT, "models", "aura_v2_sft")
    os.makedirs(output_dir, exist_ok=True)
    merged_model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Modelo SFT guardado en: {output_dir}")


if __name__ == "__main__":
    main()
