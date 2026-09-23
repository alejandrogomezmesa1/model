import json
import os
import sys
import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DPOConfig, DPOTrainer

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(base_dir, "..")) if os.path.basename(base_dir) == "src" else base_dir

    # 1. Hardware y precisión
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_dtype = torch.bfloat16 if use_bf16 else torch.float32

    # 2. Cargar el modelo que ya pasó por SFT (o el modelo base)
    candidate_sft = [
        os.path.join(project_root, "models", "mi_modelo_sft"),
        os.path.join(base_dir, "mi_modelo_sft")
    ]
    sft_model_dir = next((p for p in candidate_sft if os.path.exists(p)), None)
    if sft_model_dir:
        model_source = sft_model_dir
        print(f"Iniciando DPO sobre el modelo SFT: {model_source}")
    else:
        model_source = "Qwen/Qwen2.5-0.5B-Instruct"
        print(f"Modelo SFT no detectado, usando base: {model_source}")

    tokenizer = AutoTokenizer.from_pretrained(model_source)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_source,
        dtype=model_dtype,
    ).to(device)

    # 3. Cargar dataset_dpo.json
    candidate_dpo = [
        os.path.join(project_root, "data", "dataset_dpo.json"),
        os.path.join(base_dir, "dataset_dpo.json")
    ]
    dpo_path = next((p for p in candidate_dpo if os.path.exists(p)), candidate_dpo[0])
    print(f"Cargando pares de preferencia desde: {dpo_path}...")
    with open(dpo_path, "r", encoding="utf-8") as f:
        dpo_raw = json.load(f)

    # Formatear el prompt con el chat template oficial de Qwen
    formatted_dpo = []
    for item in dpo_raw:
        user_prompt = item.get("prompt")
        chosen_resp = item.get("chosen")
        rejected_resp = item.get("rejected")

        if not user_prompt or not chosen_resp or not rejected_resp:
            continue

        # Prompt formateado como entrada de usuario
        system_msg = (
            "Eres un maestro perfumista y químico de fragancias de alta gama. "
            "Respondes siempre en español con rigor técnico, precisión y elegancia."
        )
        messages_prompt = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt}
        ]
        prompt_str = tokenizer.apply_chat_template(messages_prompt, tokenize=False, add_generation_prompt=True)

        formatted_dpo.append({
            "prompt": prompt_str,
            "chosen": chosen_resp,
            "rejected": rejected_resp
        })

    train_dataset = Dataset.from_list(formatted_dpo)
    print(f"Dataset DPO preparado: {len(train_dataset)} pares de preferencias (chosen vs rejected).")

    # 4. Configurar LoRA para DPO
    peft_config = LoraConfig(
        r=16,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]
    )

    # 5. Configurar DPO
    checkpoints_dir = os.path.join(project_root, "checkpoints", "dpo")
    dpo_config = DPOConfig(
        output_dir=checkpoints_dir,
        beta=0.1,                     # Coeficiente KL estándar para estabilidad DPO
        learning_rate=5e-6,           # Tasa ultra-suave característica de DPO
        max_length=512,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2,
        num_train_epochs=3,
        bf16=use_bf16,
        logging_steps=2,
        report_to="none",
        save_strategy="no"
    )

    # 6. Instanciar DPOTrainer
    # Con ref_model=None y peft_config, TRL usa el modelo base congelado como referencia
    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=dpo_config,
        train_dataset=train_dataset,
        processing_class=tokenizer,
        peft_config=peft_config
    )

    print("\n--- Iniciando Fase 2: Aprendizaje por Refuerzo (DPO) ---")
    trainer.train()

    # 7. Fusionar pesos finales del modelo maestro
    print("\nFusionando adaptadores DPO en el modelo final...")
    final_model = trainer.model.merge_and_unload()

    final_dir = os.path.join(project_root, "models", "mi_modelo_perfumista_v1")
    os.makedirs(final_dir, exist_ok=True)
    final_model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"\n¡MODELO SOBERANO FINAL COMPLETADO!")
    print(f"Guardado y listo para usar en: {final_dir}")

if __name__ == "__main__":
    main()
