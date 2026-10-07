"""
Fase 2 — DPO de AURA sobre el modelo SFT (models/aura_v2_sft).

Entrena con data/aura_dpo.jsonl (generado por src/preparar_datos_aura.py): pares en formato
conversacional (prompt con el mismo sistema + contexto RAG de la API, chosen vs. rejected).
Aquí el modelo aprende qué NO hacer: filtrar costos o la concentración, dar cantidades de
formulación, decir «original», inventar productos, descuentos o medios de pago, etc.

Salida: models/aura_v2/ (modelo final que carga api.py).
"""
import os
import sys
import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DPOConfig, DPOTrainer

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class DPOTrainerRecortado(DPOTrainer):
    """DPOTrainer que solo calcula logits desde donde empieza la respuesta.

    TRL calcula los logits de toda la secuencia (~1600 tokens × 152k de vocabulario ≈ 1 GB por par en
    bf16, más su gradiente), aunque la pérdida solo usa la respuesta (~100-400 tokens). En una GPU de
    4 GB eso desborda a memoria compartida y cada paso tarda más de un minuto.

    El modelo recibe la secuencia completa (claves full_*) con logits_to_keep=K, y a la pérdida de TRL
    le llegan input_ids/máscaras recortados a las mismas K últimas posiciones, así que todo queda
    alineado: el logit de la posición L-K+j predice el token L-K+j+1.
    Requiere precompute_ref_log_probs=True (el pase de referencia no se recorta).
    """

    def _compute_loss(self, model, inputs, return_outputs):
        cm = inputs["completion_mask"]
        largo = cm.shape[1]
        inicio = int(cm.float().argmax(dim=1).min())  # primera posición de respuesta en el lote
        k = largo - inicio + 1                       # incluye el logit que predice el primer token
        if k >= largo:
            return super()._compute_loss(model, inputs, return_outputs)

        recortado = dict(inputs)
        recortado["full_input_ids"] = inputs["input_ids"]
        recortado["full_attention_mask"] = inputs["attention_mask"]
        for clave in ("input_ids", "attention_mask", "completion_mask"):
            recortado[clave] = inputs[clave][:, largo - k:]

        def modelo_recortado(full_input_ids, full_attention_mask, input_ids=None, attention_mask=None, **kw):
            return model(input_ids=full_input_ids, attention_mask=full_attention_mask, logits_to_keep=k, **kw)

        return super()._compute_loss(modelo_recortado, recortado, return_outputs)


def main():
    # 1. Hardware y precisión
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_dtype = torch.bfloat16 if use_bf16 else torch.float32

    # 2. Modelo SFT de la fase 1
    sft_dir = os.path.join(PROJECT_ROOT, "models", "aura_v2_sft")
    if not os.path.isfile(os.path.join(sft_dir, "model.safetensors")):
        raise SystemExit("Falta models/aura_v2_sft: corre primero src/train_sft.py")
    print(f"DPO sobre el modelo SFT: {sft_dir}")

    tokenizer = AutoTokenizer.from_pretrained(sft_dir)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(sft_dir, dtype=model_dtype).to(device)

    # 3. Pares de preferencia (formato conversacional; TRL aplica el chat template)
    dpo_path = os.path.join(PROJECT_ROOT, "data", "aura_dpo.jsonl")
    if not os.path.exists(dpo_path):
        raise SystemExit("Falta data/aura_dpo.jsonl: corre primero src/preparar_datos_aura.py")
    train_dataset = load_dataset("json", data_files=dpo_path, split="train")
    print(f"Dataset DPO: {len(train_dataset)} pares (chosen vs rejected)")

    # 4. LoRA (con ref_model=None, TRL usa el modelo SFT sin adaptador como referencia)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    # 5. DPO. max_length=2048 cubre el par más largo (~1700 tokens) sin cortar.
    dpo_config = DPOConfig(
        output_dir=os.path.join(PROJECT_ROOT, "checkpoints", "aura_dpo"),
        beta=0.1,
        # Los pares rechazados son fallas burdas y fáciles de separar: con lr 2e-5 y 2 épocas el margen
        # llegó a 8 y el modelo se degradó (mezcla de idiomas, alucinaciones). Por eso lr bajo, 1 época
        # y una pérdida SFT sobre la respuesta elegida que ancla el lenguaje (estilo RPO).
        learning_rate=5e-6,
        loss_type=["sigmoid", "sft"],
        loss_weights=[1.0, 1.0],
        lr_scheduler_type="cosine",
        warmup_steps=0.1,  # fracción del total de pasos
        max_length=2048,
        gradient_checkpointing=True,
        # Los log-probs de referencia se calculan una vez al inicio: así cada paso no carga los logits
        # (~1 GB por par) del modelo de referencia además de los del modelo, y cabe en 4 GB de VRAM.
        precompute_ref_log_probs=True,
        precompute_ref_batch_size=1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=1,
        bf16=use_bf16,
        logging_steps=5,
        report_to="none",
        save_strategy="no",
    )

    trainer = DPOTrainerRecortado(
        model=model,
        ref_model=None,
        args=dpo_config,
        train_dataset=train_dataset,
        processing_class=tokenizer,
        peft_config=peft_config,
    )

    print("\n--- Fase 2: DPO de AURA ---")
    trainer.train()

    # 6. Fusionar y guardar el modelo final
    final_model = trainer.model.merge_and_unload()
    final_dir = os.path.join(PROJECT_ROOT, "models", "aura_v2")
    os.makedirs(final_dir, exist_ok=True)
    final_model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"Modelo final de AURA guardado en: {final_dir}")


if __name__ == "__main__":
    main()
