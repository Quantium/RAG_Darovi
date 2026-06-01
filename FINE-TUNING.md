# FINE-TUNING.md — Proposal: Fine-tuned Document → PostgreSQL Structuring Model

> **Status:** Proposal / RFC. Nothing here is wired into the codebase yet.
> **Scope of this document:** design, training, and deployment plan only. No code outside this file is changed.
> **Language note:** Written in English per the repository's *English documentation* constraint (`CLAUDE.md`). Spanish domain field names (e.g. *Denominación Genérica*) are preserved verbatim because they are the literal labels printed on the source documents.

---

## 1. Executive Summary

We want a model that reads an (often scanned, OCR'd, Spanish) regulatory/tender document and emits **structured JSON** that maps cleanly into PostgreSQL rows, linked to the official **COEPRIS** registry data and to our **internal medication IDs**.

**Recommendation in one paragraph:** Fine-tune a small open instruct model (**Llama 3.1 8B Instruct** as the primary candidate) with **Unsloth + QLoRA**, using the `master` Excel as the labelling oracle. Train iteratively for free/cheap on **Google Colab / Kaggle notebooks**, promote serious runs to **SageMaker Training Jobs** or **EC2 spot**. Because document extraction is a **batch ETL workload — not interactive chat**, deploy for inference on **Amazon Bedrock Custom Model Import** (serverless, scale-to-zero, lowest ops) as the primary path, with **SageMaker Batch Transform / Asynchronous Inference** as the cost-optimal batch alternative and **self-hosted vLLM on EC2/on-prem** as the data-sovereignty floor. Crucially, **the model should extract natural-key fields only; resolving the internal medication ID is a deterministic join against the master table, not a memorization task for the model.**

**Estimated cost:** training is effectively negligible (< US$20 per run, often $0 on free tiers). Ongoing inference for ~5,000 documents/month lands at **~US$5–15/month** (SageMaker Batch) to **~US$50–130/month** (Bedrock CMI serverless), versus ~US$730/month for a naive always-on endpoint. Details in §15.

---

## 2. Objective and Success Criteria

**Objective.** Convert unstructured document content into validated, structured records in PostgreSQL, enriched and reconciled with COEPRIS official data and our internal medication IDs.

**Success criteria (quality gates).** A run is promotable only if, on a held-out test set:

| Metric | Target |
|---|---|
| JSON validity rate (parses + passes Pydantic schema) | ≥ 99% |
| Per-field exact match (key fields: *registro sanitario*, *denominación genérica/distintiva*) | ≥ 95% |
| Field-level precision / recall (macro) | ≥ 0.92 |
| Hallucinated-value rate (value not present in source text) | ≤ 1% |
| Internal-ID resolution accuracy (after deterministic join) | ≥ 98% |
| Cost per 1,000 documents | ≤ baseline frontier-API cost |

These gates are mandatory: a fine-tune is only worthwhile if it beats the **baseline** (§6) on accuracy-per-dollar.

---

## 3. Current System Context (grounded in this repo)

The proposal plugs into the existing monorepo, not around it.

- **Domain.** COFEPRIS/COEPRIS sanitary registrations for pharmaceutical *licitaciones*. The chatbot system prompt (`services/chatbot_response/app/llm.py`) already enumerates the canonical fields we must extract: **Denominación Distintiva, Denominación Genérica, número de registro sanitario, titular, fabricante, número de solicitud**.
- **Pipeline today.** `ingest_raw` → `extract_text` (pdfplumber / docx / xlsx, with GPT‑4o vision OCR for scanned pages) → embed → Milvus (Zilliz). Text is OCR'd Spanish Markdown, page-segmented, sometimes noisy.
- **State machine** (`file_records`): `raw_status`, `text_status`, `status`. Today the chain ends at `embedded`. **This proposal adds a structured-extraction stage** (see §13).
- **Existing target table.** `schema/rag-schema/alembic/versions/20260515_0001_baseline_schema.py` already defines a *generic* placeholder:
  ```python
  extracted_documents(
      drive_file_id PK/FK, document_type, issuer, issued_at,
      total_amount, currency, parties JSON, extras JSON, extracted_at
  )
  ```
  This is too generic for the pharma domain. §11 proposes a domain-specific schema. **Per `CLAUDE.md`, any schema change goes through Alembic in `schema/rag-schema` and must be approved before implementation — this document only proposes it.**
- **Feedback loop already exists.** `chat_interactions(question, answer, rating, correction, ...)` (migration `20260525_0004`) is a ready-made source of human corrections we can recycle into training data (§7, active learning).
- **Stack facts that constrain deployment.** PostgreSQL on **Neon**, vectors on **Zilliz**, **AWS EC2** already in use (`docker-compose.aws.yml`), Python managed by **`uv`**, OpenAI (embeddings + vision) and DeepSeek (chat) already integrated. No GPU is currently in the stack.

---

## 4. The `master` Excel as the Labelling Oracle

The `master` workbook is the single most valuable asset here. It contains, per row:

1. Fields **extracted from the documents** (the model's target outputs),
2. Fields **pulled from the official COEPRIS database** (authoritative reconciliation values),
3. **Internal IDs** linking each medication to our internal identifiers.

This gives us, essentially for free, a **supervised dataset**: for each document we can construct a `(document_text → structured_JSON)` training pair, where the JSON is the master row. It also doubles as the **resolution table** for the deterministic ID-mapping step (§9).

> The `master` file is **not** committed to the repo (data is gitignored). It will be the input to the dataset-builder script (§7), which must run where the file lives.

**Three roles of `master`:**

| Role | Used in | Notes |
|---|---|---|
| Training labels | Dataset builder (§7) | Document-derived fields become the JSON target. |
| Reconciliation source | Deterministic resolver (§9) | COEPRIS values validate/correct model output. |
| ID lookup table | Deterministic resolver (§9) | Maps natural keys → `internal_medication_id`. |

---

## 5. Why Fine-tune at All? (and the honest alternative)

Fine-tuning is justified **only** when at least one of these holds: (a) per-document cost at scale is too high with a frontier API, (b) data must stay private/on-prem, (c) latency/throughput needs a local model, or (d) domain-specific OCR'd Spanish defeats general models on the key fields.

This task plausibly satisfies (a), (b) and (d): high document volume, sensitive tender data, and messy domain-specific OCR. A 7–8B model fine-tuned on in-domain pairs is the textbook sweet spot for **closed-schema extraction**.

**But the recommended standard is to measure the baseline first** (§6) — it is cheap, sets the bar every fine-tune must beat, and is also your best *teacher* for synthetic-data generation.

---

## 6. Recommended Standard / Best Practices for This Class of Project

These are the practices we should treat as non-negotiable for an extraction fine-tune:

1. **Baseline before fine-tune.** Benchmark a strong instruct model (e.g. the DeepSeek/OpenAI APIs already wired in) with *structured outputs* (JSON-schema / function-calling) + few-shot, on the held-out test set. Every fine-tune must beat this on accuracy-per-dollar.
2. **Closed schema, validated with Pydantic.** Define the output contract once (§11) and validate every generation. Invalid JSON → automatic repair/retry, never a silent write.
3. **Constrained / guided decoding at inference.** Don't *hope* for valid JSON — *enforce* it (vLLM guided decoding / XGrammar / Outlines / llama.cpp GBNF grammar). This single practice removes most JSON-validity failures. (Bedrock CMI does not constrain decoding, so there we validate + retry instead — see §13.)
4. **Separate extraction from entity resolution.** The model extracts what's *on the page* (registro sanitario, denominación, etc.). Mapping to `internal_medication_id` / `coepris_id` is a **deterministic join + fuzzy match** against `master`. Do not make the model memorize ID mappings — it is brittle, unauditable, and breaks when the catalog changes.
5. **Train ≈ serve precision.** Unsloth's guidance: if you serve in 4-bit, train in 4-bit; if you serve 16-bit (vLLM/Bedrock), prefer LoRA→merged 16-bit. Mismatched precision degrades accuracy.
6. **No leakage in splits.** Split by *document* (and ideally by *titular/fabricante*), never by row, so near-duplicate pages don't straddle train/test.
7. **Deterministic serialization of targets.** Sorted keys, explicit `null` for absent fields, canonical date format (`YYYY-MM-DD`), no trailing whitespace. The model should learn one canonical surface form.
8. **Negatives and "absent" cases.** Include documents where a field is genuinely missing → target `null`. Otherwise the model learns to hallucinate.
9. **Field-level evaluation, not just loss.** Track per-field precision/recall/exact-match and JSON-validity, versioned per run.
10. **Reproducibility + provenance.** Fixed seed (`3407`), pinned deps via `uv`, dataset version hash, model card, experiment tracking (Weights & Biases or MLflow).
11. **Human-in-the-loop flywheel.** Route low-confidence extractions to review; feed corrections (incl. `chat_interactions.correction`) back into the next dataset version (active learning).
12. **Start small, scale only if needed.** Begin at 8B/QLoRA. Only move to larger models or full fine-tuning if the eval gates demand it — "LoRA can match full fine-tuning" for narrow tasks.

---

## 7. Dataset Construction

### 7.1 Pair shape

We fine-tune as **instruction SFT** with a chat template. Each example:

- **system:** role + strict "extract only what is present, output JSON only" instruction.
- **user:** the OCR'd document text (or a page/section chunk) + the JSON schema.
- **assistant:** the canonical target JSON (from the `master` row).

Conceptual target schema (full definition in §11):

```json
{
  "document_type": "registro_sanitario",
  "denominacion_distintiva": "…",
  "denominacion_generica": "…",
  "registro_sanitario": "…",
  "numero_solicitud": "…",
  "titular": "…",
  "fabricante": "…",
  "forma_farmaceutica": "…",
  "presentacion": "…",
  "principios_activos": ["…"],
  "fecha_emision": "YYYY-MM-DD",
  "fecha_vigencia": "YYYY-MM-DD"
}
```
> Note: `internal_medication_id` and `coepris_id` are intentionally **not** model outputs — they are added by the deterministic resolver (§9).

### 7.2 Builder script (runs where `master` lives; uses `uv`)

Pseudocode for `scripts/build_finetune_dataset.py` (to be created later, outside this proposal):

```python
# uv run scripts/build_finetune_dataset.py --master master.xlsx --out dataset.jsonl
# 1. Load master.xlsx (openpyxl/pandas).
# 2. For each row, locate the source document text:
#      - prefer MinIO converted-texts (minio_text_key) keyed via file_records,
#      - or re-extract with services/extract_text/app/extractors.extract_text().
# 3. Build the canonical JSON target from the document-derived columns ONLY.
# 4. Emit ShareGPT-style rows -> JSONL:
#    {"conversations":[{"role":"system",...},{"role":"user",...},{"role":"assistant", "<canonical json>"}]}
# 5. Split by document id (group-aware): 80% train / 10% val / 10% test.
# 6. Write train.jsonl / val.jsonl / test.jsonl + a dataset_version hash.
```

### 7.3 Size and augmentation

- **Minimum** ~100 rows for a signal; **1,000+ rows** for good results; more is better *if clean* (Unsloth guidance).
- If real labelled pairs are scarce, **augment synthetically**: use the baseline model (or Unsloth's *Synthetic Dataset* notebook, which parses PDFs and auto-generates/cleans pairs) to expand coverage of rare document layouts. Always human-spot-check synthetic data and balance field coverage.
- Recycle `chat_interactions.correction` rows as gold corrections.

### 7.4 Canonicalization rules (enforced in the builder)

- Dates → `YYYY-MM-DD` or `null`.
- Missing field → explicit `null` (never omit the key).
- `principios_activos` → list, deduplicated, trimmed.
- Keys sorted; assistant content is `json.dumps(obj, ensure_ascii=False, sort_keys=True)`.

---

## 8. Model Selection

| Candidate | Size | Why | Bedrock CMI import? |
|---|---|---|---|
| **Llama 3.1 8B Instruct** (primary) | 8B | Unsloth's beginner-recommended baseline; strong multilingual incl. Spanish; **explicitly supported** by Bedrock Custom Model Import (Llama 3.x). | ✅ Yes |
| Qwen2.5 7B / Qwen3 8B (alt) | 7–8B | Excellent at structured/JSON output, strong multilingual. | ⚠️ Verify current Bedrock arch support; if unsupported, deploy via SageMaker/vLLM. |
| Mistral 7B v0.3 (alt) | 7B | Supported by Bedrock CMI (Mistral arch); lean. | ✅ Yes |
| Llama 3.2 3B (cost floor) | 3B | If 8B is overkill and throughput/cost dominate. | ✅ Yes |

**Decision:** start with **Llama 3.1 8B Instruct (4-bit)**. It is supported end-to-end (Unsloth training → Bedrock deployment), handles Spanish well, and fits a free Colab T4 for QLoRA. Re-evaluate Qwen2.5-7B as a challenger if extraction accuracy needs a lift (but confirm Bedrock support before committing to that deployment path).

**Context length.** OCR'd tender docs can be long. Train at `max_seq_length = 4096–8192` and **chunk long documents page-wise** (the pipeline already segments pages), extracting per page/section then merging — cheaper and matches the existing OCR granularity.

---

## 9. Architecture: Extraction + Deterministic Resolution

```
            ┌─────────────────────────┐      ┌──────────────────────────┐      ┌───────────────┐
OCR text ─▶ │ Fine-tuned 8B extractor │ ─▶   │ Pydantic validate/repair │ ─▶   │  Deterministic │ ─▶ PostgreSQL
 (Markdown) │  (guided JSON decoding) │ JSON │   (retry if invalid)     │ obj  │   resolver     │     upsert
            └─────────────────────────┘      └──────────────────────────┘      │ (join master/  │
                                                                                │  COEPRIS →     │
                                                                                │  internal IDs) │
                                                                                └───────────────┘
```

- **Extractor** = the fine-tuned model. Outputs natural-key fields only.
- **Validator** = Pydantic schema (§11). Invalid → repair prompt / retry, bounded attempts, else flag for human review.
- **Resolver** = deterministic. Exact match on `registro_sanitario`; fallback fuzzy match on `denominación + titular + presentación` against `master`/COEPRIS; emits `internal_medication_id`, `coepris_id`, and a `match_confidence`. Low confidence → human review queue.

This keeps the learned part small and auditable, and the brittle part (ID mapping) deterministic and catalog-driven.

---

## 10. Fine-tuning Method and Hyperparameters (Unsloth)

**Method:** **QLoRA** (4-bit) first — most accessible, fits free Colab, and "LoRA can match full fine-tuning" for narrow extraction. Move to LoRA/16-bit or full fine-tuning only if eval gates require it.

Recommended starting hyperparameters (Unsloth defaults + extraction-tuned):

| Hyperparameter | Value | Rationale |
|---|---|---|
| `r` (LoRA rank) | 16 (try 32) | Capacity vs. memory; 16/32 is the sweet spot. |
| `lora_alpha` | 16 (= `r`) or 32 (= `2r`) | Standard scaling heuristic. |
| `lora_dropout` | 0 | Unsloth default; dropout rarely helps here. |
| `target_modules` | `q,k,v,o_proj` + `gate,up,down_proj` | Attention + MLP (full coverage). |
| `learning_rate` | 2e-4 (QLoRA) | Typical for LoRA SFT. |
| `num_train_epochs` | 2–3 | Watch overfitting on a closed schema. |
| `per_device_train_batch_size` | 2 | Fits T4/A10G at seqlen 4096. |
| `gradient_accumulation_steps` | 4 | Effective batch 8. |
| `warmup_ratio` | 0.05 | 5–10% of steps. |
| `weight_decay` | 0.01 | Regularization. |
| `lr_scheduler_type` | linear (or cosine) | Either is fine. |
| `optim` | `adamw_8bit` | Memory-efficient. |
| `seed` | 3407 | Reproducibility. |
| `max_seq_length` | 4096–8192 | Per-page/section extraction. |

**Train on responses only** (mask the prompt) so the loss focuses on the JSON, not on re-predicting the document text.

---

## 11. Proposed Target Schema (Pydantic + PostgreSQL)

> **Schema-safety reminder (`CLAUDE.md`):** this is a *proposal*. The actual table/migration must be created in `schema/rag-schema` via Alembic and approved first.

**Pydantic contract** (used for validation and for guided decoding):

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

class MedicationExtraction(BaseModel):
    document_type: Literal["registro_sanitario", "oficio", "factura", "anexo_tecnico", "otro"]
    denominacion_distintiva: str | None = None
    denominacion_generica:  str | None = None
    registro_sanitario:     str | None = None
    numero_solicitud:       str | None = None
    titular:                str | None = None
    fabricante:             str | None = None
    forma_farmaceutica:     str | None = None
    presentacion:           str | None = None
    principios_activos:     list[str] = Field(default_factory=list)
    fecha_emision:          date | None = None
    fecha_vigencia:         date | None = None
```

**Proposed PostgreSQL mapping** (new table; resolver fills the ID columns):

```sql
-- PROPOSAL ONLY — implement via Alembic in schema/rag-schema after approval.
CREATE TABLE medication_extractions (
    drive_file_id           text PRIMARY KEY REFERENCES file_records(drive_file_id) ON DELETE CASCADE,
    document_type           text,
    denominacion_distintiva text,
    denominacion_generica   text,
    registro_sanitario      text,
    numero_solicitud        text,
    titular                 text,
    fabricante              text,
    forma_farmaceutica      text,
    presentacion            text,
    principios_activos      jsonb NOT NULL DEFAULT '[]'::jsonb,
    fecha_emision           date,
    fecha_vigencia          date,
    -- filled by the deterministic resolver, NOT the model:
    internal_medication_id  text,
    coepris_id              text,
    match_confidence        numeric(5,4),
    model_version           text,        -- provenance
    extraction_status       text NOT NULL DEFAULT 'pending_review',
    extracted_at            timestamptz NOT NULL DEFAULT now()
);
```
(Alternatively, store the raw model JSON in `extracted_documents.extras` to avoid a new table — but a typed table is cleaner for downstream SQL and the tender use case.)

---

## 12. Training Environments

The user requires **Colab notebooks**; below they are option (A), with several local/cloud alternatives.

| # | Environment | GPU | Cost model | Best for |
|---|---|---|---|---|
| **A** | **Google Colab** (Pro / Pro+ / PAYG) | T4 16GB (free) → L4 → A100 40GB | $9.99/100 CU; Pro $9.99/mo; Pro+ $49.99/mo | **Required.** Fast iteration, demos, the deliverable notebook. |
| B | **Kaggle Notebooks** | 2×T4 16GB or P100 | Free (~30 GPU-hr/week) | Free QLoRA 8B runs, longer than free Colab. |
| C | **SageMaker Training Jobs** | ml.g5/g6 (A10G/L4) | per-second; spot up to ~70% off | Reproducible production training inside AWS, artifacts to S3. |
| D | **EC2 GPU spot** | g5.xlarge (A10G), g6.xlarge (L4) | ~$0.25–0.40/hr spot | Cheapest cloud GPU; DIY (Unsloth Docker image). |
| E | **Local workstation** | RTX 4090/5090 (24–32GB) | electricity only | Data privacy, zero marginal cost — *if hardware exists*. |
| F | **RunPod / Lambda / Modal / Vast.ai** | A100 40/80GB | ~$1.2–2/hr on-demand | On-demand big-GPU when you outgrow Colab; often cheaper than AWS for training. |

**Recommended workflow:** prototype on **Colab/Kaggle (free)** → promote the winning recipe to **SageMaker Training Jobs (spot)** or **EC2 spot** for the official, versioned run that produces the deployable artifact. All Python via **`uv`** (per `CLAUDE.md`); the official [Unsloth Docker image](https://hub.docker.com/r/unsloth/unsloth) standardizes the env across D/E/F.

**VRAM reality check:** QLoRA on an 8B model fits a **free Colab T4 (16GB)** at modest seqlen; an A100 40GB does it comfortably at seqlen 8192. Unsloth supports NVIDIA GPUs from 2018+ (CUDA capability ≥ 7.0), Linux/Windows, Python 3.13.

---

## 13. Colab Notebook Blueprint (the deliverable training notebook)

A single `finetune_coepris_extractor.ipynb` to run in Colab. The cells below are the algorithm; paste them into the notebook. (They also run on Kaggle/EC2/local unchanged.)

**Cell 1 — install**
```python
%pip install unsloth
# Unsloth pulls compatible torch / transformers / trl / bitsandbytes / xformers automatically.
```

**Cell 2 — load base model (QLoRA, 4-bit)**
```python
from unsloth import FastLanguageModel
import torch

max_seq_length = 4096
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit",
    max_seq_length = max_seq_length,
    load_in_4bit = True,     # QLoRA
    dtype = None,            # auto (bf16 on Ampere+)
)
```

**Cell 3 — attach LoRA adapters**
```python
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj","k_proj","v_proj","o_proj",
                      "gate_proj","up_proj","down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)
```

**Cell 4 — load dataset + chat template**
```python
from datasets import load_dataset
from unsloth.chat_templates import get_chat_template

tokenizer = get_chat_template(tokenizer, chat_template = "llama-3.1")

# train.jsonl / val.jsonl produced by scripts/build_finetune_dataset.py (§7).
data = load_dataset("json", data_files={"train":"train.jsonl","val":"val.jsonl"})

def formatting_prompts_func(examples):
    texts = [
        tokenizer.apply_chat_template(c, tokenize=False, add_generation_prompt=False)
        for c in examples["conversations"]
    ]
    return {"text": texts}

data = data.map(formatting_prompts_func, batched=True)
```

**Cell 5 — train (response-only loss)**
```python
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

trainer = SFTTrainer(
    model = model, tokenizer = tokenizer,
    train_dataset = data["train"], eval_dataset = data["val"],
    args = SFTConfig(
        dataset_text_field = "text",
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_ratio = 0.05,
        num_train_epochs = 3,
        learning_rate = 2e-4,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        logging_steps = 10,
        seed = 3407,
        output_dir = "outputs",
        max_seq_length = max_seq_length,
        report_to = "wandb",   # experiment tracking
    ),
)
trainer = train_on_responses_only(
    trainer,
    instruction_part = "<|start_header_id|>user<|end_header_id|>\n\n",
    response_part    = "<|start_header_id|>assistant<|end_header_id|>\n\n",
)
trainer.train()
```

**Cell 6 — quick sanity inference**
```python
FastLanguageModel.for_inference(model)
msgs = [
    {"role":"system","content": SYSTEM_PROMPT},
    {"role":"user","content": build_user_prompt(sample_document_text)},
]
inputs = tokenizer.apply_chat_template(msgs, add_generation_prompt=True,
                                       return_tensors="pt").to("cuda")
print(tokenizer.decode(model.generate(input_ids=inputs, max_new_tokens=512)[0]))
```

**Cell 7 — export artifacts**
```python
# (a) LoRA adapter only (~100MB) — cheap to store/version
model.save_pretrained("lora_model"); tokenizer.save_pretrained("lora_model")

# (b) Merged 16-bit safetensors — REQUIRED for vLLM and Bedrock Custom Model Import
model.save_pretrained_merged("merged_16bit", tokenizer, save_method="merged_16bit")

# (c) GGUF (q4_k_m) — for local Ollama / llama.cpp testing
model.save_pretrained_gguf("gguf_model", tokenizer, quantization_method="q4_k_m")

# (d) Optional: push to Hugging Face Hub
# model.push_to_hub_merged("org/coepris-extractor-8b", tokenizer,
#                          save_method="merged_16bit", token=HF_TOKEN)
```

A **second notebook**, `eval_coepris_extractor.ipynb`, runs the held-out `test.jsonl` through the model and computes the §2 metrics (JSON validity, per-field exact-match, precision/recall) and compares against the baseline.

---

## 14. Export & Packaging Matrix

| Artifact | Produced by | Consumed by |
|---|---|---|
| LoRA adapter (~100 MB) | `save_pretrained` | version control of "the diff"; re-merge anytime |
| Merged 16-bit safetensors | `save_pretrained_merged(..., "merged_16bit")` | **vLLM**, **SageMaker**, **Bedrock CMI** (S3 import) |
| GGUF q4_k_m | `save_pretrained_gguf` | **Ollama / llama.cpp** local testing & on-prem CPU/GPU |
| FP8 / AWQ | vLLM quantization | high-throughput multi-user serving |

**Train ≈ serve precision:** since Bedrock/vLLM serve 16-bit, prefer merging to 16-bit (or quantize *consistently* to FP8/AWQ and validate accuracy didn't regress).

---

## 15. Deployment on AWS — Options Analysis & Recommendation

**Key insight:** this is **batch ETL**, not interactive chat. Documents flow through the pipeline; extraction does not need millisecond latency. That reframes the cost question entirely — a 24/7 endpoint is almost always the wrong answer.

### 15.1 Option comparison

| Option | What it is | Ops burden | Scales to zero? | Schema-constrained decoding | Best when |
|---|---|---|---|---|---|
| **Bedrock Custom Model Import (CMI)** ⭐ primary | Import merged weights; serverless on-demand `InvokeModel` | **None** | **Yes** (idle → 0) | No (validate+retry) | Low-ops, spiky/moderate volume, want it inside Bedrock (Guardrails/KB/Agents) |
| **SageMaker Batch Transform** ⭐ cost-optimal batch | Offline job over a dataset, no persistent endpoint | Low | N/A (ephemeral) | Yes (vLLM/LMI container) | Large nightly/periodic batches → cheapest per doc |
| **SageMaker Asynchronous Inference** | Queue-based endpoint, scales to 0 when idle | Low–Med | **Yes** | Yes | Variable arrival, near-real-time, payloads ≤ 1GB |
| **SageMaker Real-time + scale-to-zero** | Persistent endpoint, can scale to 0 | Med | Yes (new feature) | Yes | If you later need low-latency interactive extraction |
| **Self-host vLLM on EC2 / on-prem** | You run the container | High | Manual | Yes | Data sovereignty / lowest raw cost / reuse existing EC2 |

**Notes that matter:**
- **Bedrock CMI** supports Mistral, Mixtral, Llama 2/3/3.1/3.2/3.3 (and more); regions **us-east-1, us-east-2, us-west-2, eu-central-1**. It **cannot** use the Bedrock *Batch inference* feature — but you can still loop `InvokeModel` over documents; Bedrock keeps copies warm during the burst and scales to zero after. **Cold start** is tens of seconds (minutes for larger models) — fine for batch, not for sub-second SLAs.
- **Batch Transform / Async** give full control of the serving container (vLLM with **guided JSON decoding**), so JSON validity is enforced at the source.

### 15.2 Recommendation

1. **Default / primary: Amazon Bedrock Custom Model Import.** Serverless, scale-to-zero, no infrastructure, native to the existing AWS footprint, simplest integration (one `InvokeModel` call from a new Celery task or microservice). Validate output with Pydantic + bounded retry since CMI doesn't constrain decoding.
2. **When volume grows / for big periodic runs: SageMaker Batch Transform** with a vLLM container and **guided decoding** — the cheapest per-document option and the cleanest JSON guarantee.
3. **For variable, near-real-time arrival: SageMaker Asynchronous Inference** (scale-to-zero).
4. **For data sovereignty or cost floor: self-host vLLM** on an EC2 GPU (or on-prem if a GPU is acquired), run only during batch windows.

Avoid a naive always-on real-time endpoint unless an interactive SLA appears.

### 15.3 Bedrock import sketch
```bash
# 1. Upload merged 16-bit weights to S3
aws s3 sync ./merged_16bit s3://<bucket>/coepris-extractor-8b/

# 2. Create the import job (console or CLI) -> creates an on-demand custom model
aws bedrock create-model-import-job \
  --job-name coepris-extractor-8b-v1 \
  --imported-model-name coepris-extractor-8b \
  --model-data-source 's3DataSource={s3Uri=s3://<bucket>/coepris-extractor-8b/}' \
  --role-arn arn:aws:iam::<acct>:role/<bedrock-import-role>

# 3. Invoke (validate JSON client-side, retry on failure)
aws bedrock-runtime invoke-model --model-id <imported-model-arn> \
  --body '{"prompt":"<chat-formatted prompt>","max_gen_len":512,"temperature":0}' out.json
```

---

## 16. Integration with the Existing Pipeline

Add a new stage to the `file_records` state machine, mirroring the existing poll-based design (Celery beat already polls `poll_text_ready_for_embedding`):

```
text_status: ready_for_embedding ─▶ extraction_queued ─▶ extracting ─▶ extracted
                                                                       └▶ extraction_review  (low confidence / invalid)
```

- A new poller (`poll_text_ready_for_extraction`) picks rows with usable text, calls the model (Bedrock `InvokeModel` or SageMaker), validates with Pydantic, runs the deterministic resolver (§9), and upserts into `medication_extractions`.
- Mirror the service layout (`services/<name>/app/...` + `settings.py` with `pydantic-settings`); add env vars to **both** `.env.example` and the per-service settings (per `CLAUDE.md`), e.g. `EXTRACTION_PROVIDER`, `EXTRACTION_MODEL_ID`, `EXTRACTION_ENDPOINT`, AWS creds/region.
- The new table + state values land via an **Alembic migration in `schema/rag-schema`** — **requires approval before implementation** (`CLAUDE.md` schema-safety rule); migrations run automatically on EC2 deploy.

---

## 17. Cost Estimates (approximate — verify against live pricing)

> All figures are planning estimates; cloud prices change and vary by region. Confirm on the [Bedrock](https://aws.amazon.com/bedrock/pricing/) and [SageMaker](https://aws.amazon.com/sagemaker/pricing/) pricing pages before budgeting.

### 17.1 Training cost (one-time per iteration)

QLoRA on 8B over ~1k–5k examples, 2–3 epochs ≈ **1–4 GPU-hours**.

| Environment | GPU | Rate | Per run | Notes |
|---|---|---|---|---|
| Colab Pro+ | A100 40GB | $49.99/mo (500 CU; A100 ≈ 15 CU/hr) | ~$2–6 in CU (or covered by sub) | required path |
| Colab PAYG | T4 / L4 / A100 | $9.99 / 100 CU | ~$1.5–6 | flexible |
| Kaggle | 2×T4 / P100 | free (~30 hr/wk) | **$0** | best free option |
| SageMaker Training | ml.g5.2xlarge | ~$1.5–2/hr (spot −70%) | ~$3–8 (≈$1–3 spot) | versioned prod run |
| EC2 g5.xlarge spot | A10G 24GB | ~$0.30–0.40/hr | ~$1–2 | cheapest cloud |
| RunPod/Modal | A100 80GB | ~$1.2–2/hr | ~$2–8 | big GPU on demand |
| Local | RTX 4090/5090 | electricity | ~$0 | privacy, if available |

**Takeaway:** training is essentially free-to-trivial. Iterate aggressively.

### 17.2 Inference cost — representative scenario

**Assumptions** (state them, they drive everything): **5,000 documents/month**, avg ~2,000 input tokens (OCR Markdown) + ~500 output tokens (JSON), planning throughput ≈ **1,000 docs per GPU-hour** with vLLM batching on one 24GB GPU (long documents reduce this — treat as a rough planning number). → **~5 active GPU-hours/month**.

| Deployment | Unit price | Billed time | **Est. monthly** | Notes |
|---|---|---|---|---|
| **SageMaker Batch Transform** (ml.g5.xlarge) | ~$1.0–1.4/hr | ~5–8 hr | **~$7–12** | cheapest; pure offline batch |
| **EC2 g6.xlarge spot**, batch window only | ~$0.25/hr | ~6 hr | **~$2–5** + mgmt | lowest raw cost; high ops |
| **SageMaker Async** (scale-to-zero) | ~$1.0–1.4/hr | ~6–10 hr | **~$8–15** | near-real-time, variable load |
| **Bedrock CMI** (Llama 8B = 2 CMU) | $0.0785 / CMU-min | ~5 hr active + idle/cold-start windows | **~$50–130** | serverless, **zero ops**; + monthly weight storage |
| **SageMaker real-time always-on** (ml.g5.xlarge) | ~$1.0–1.4/hr | 730 hr | **~$730–1,030** | ❌ avoid for batch |
| EC2 g6.xlarge on-demand 24/7 | ~$0.80/hr | 730 hr | ~$587 | ❌ avoid unless interactive |

**CMU reference:** Llama 3.1 8B ≈ **2 CMU**, Llama 3.1 70B ≈ 8 CMU; CMU billed in 5-minute windows at ~$0.0785/CMU-min, scaling to zero when idle, plus a monthly per-version storage fee; **no charge to import**.

**Reading the table:** for cost-minimization on pure batch, **SageMaker Batch Transform or EC2 spot** win (~$2–12/mo). For **minimum operational overhead**, **Bedrock CMI** (~$50–130/mo, zero servers) is the pragmatic default and integrates with the existing AWS stack. The frontier-API baseline (DeepSeek/OpenAI) at ~2.5k tokens/doc × 5k docs is also worth pricing as the comparison floor in §6.

### 17.3 SageMaker Savings Plans
Up to **~64%** off SageMaker ML instance usage with a commitment — relevant only if you converge on a steady SageMaker footprint.

---

## 18. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OCR noise corrupts inputs | Train *on* noisy OCR (it matches production); keep the existing GPT‑4o vision fallback; add OCR-robustness examples. |
| Model hallucinates field values | Guided decoding + Pydantic validation + "value must appear in source" check; include `null`/absent negatives. |
| Internal-ID mapping drift | IDs come from the deterministic resolver against `master`, never the model; refresh the lookup table on catalog updates. |
| Schema change breaks pipeline | Versioned schema + model; Alembic migration with approval; `model_version` column for provenance. |
| Overfitting (closed schema, small data) | 2–3 epochs, weight decay, group-aware splits, watch eval loss + field metrics. |
| Bedrock cold starts | Acceptable for batch; for latency-sensitive needs use SageMaker real-time/async or keep a warm copy. |
| Data sovereignty (sensitive tenders) | Self-host vLLM on-prem/EC2 option; or keep within chosen AWS region; review licenses (Llama/Qwen/Mistral terms). |

---

## 19. Phased Roadmap

1. **Phase 0 — Baseline (1–2 days).** Build `test.jsonl` from `master`; benchmark the existing DeepSeek/OpenAI APIs with structured outputs. Record the bar.
2. **Phase 1 — Dataset (2–4 days).** Implement `build_finetune_dataset.py`; produce train/val/test with canonicalization + group-aware split + a dataset version hash.
3. **Phase 2 — Train on Colab (1–3 days).** Run `finetune_coepris_extractor.ipynb` (Llama 3.1 8B QLoRA); evaluate vs. baseline.
4. **Phase 3 — Promote + export (1–2 days).** Re-run on SageMaker/EC2 spot for the official artifact; merge to 16-bit; (optional) GGUF for local tests.
5. **Phase 4 — Deploy (2–3 days).** Bedrock CMI import (or SageMaker Batch) + Pydantic validation + deterministic resolver; integrate as a new pipeline stage (proposed Alembic migration → approval).
6. **Phase 5 — Flywheel (ongoing).** Human-review queue for low-confidence rows; recycle `chat_interactions.correction`; periodic re-train on the growing dataset.

---

## 20. References

- Unsloth — Fine-tuning Guide: https://docs.unsloth.ai/get-started/fine-tuning-llms-guide
- Unsloth — LoRA Hyperparameters Guide: https://docs.unsloth.ai/get-started/beginner-start-here/lora-hyperparameters-guide
- Unsloth — Datasets Guide: https://docs.unsloth.ai/basics/datasets-guide
- Unsloth — Inference & Deployment (saving GGUF/vLLM/Ollama): https://docs.unsloth.ai/basics/running-and-saving-models
- Unsloth — Notebooks (Colab list, incl. Synthetic Dataset): https://docs.unsloth.ai/get-started/unsloth-notebooks
- Unsloth — Requirements / VRAM: https://docs.unsloth.ai/get-started/beginner-start-here/unsloth-requirements
- Unsloth — Docker image: https://hub.docker.com/r/unsloth/unsloth
- AWS — Bedrock Custom Model Import (supported architectures, regions): https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-import-model.html
- AWS — Bedrock Custom Model Import (features): https://aws.amazon.com/bedrock/custom-model-import/
- AWS — Bedrock: calculate cost of a custom model (CMU formula): https://docs.aws.amazon.com/bedrock/latest/userguide/import-model-calculate-cost.html
- AWS — Bedrock pricing: https://aws.amazon.com/bedrock/pricing/
- AWS — SageMaker pricing: https://aws.amazon.com/sagemaker/pricing/
- AWS — SageMaker Asynchronous Inference: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html
- AWS — SageMaker scale-down-to-zero: https://aws.amazon.com/blogs/machine-learning/unlock-cost-savings-with-the-new-scale-down-to-zero-feature-in-amazon-sagemaker-inference/
- AWS — Bedrock CMI case study (Salesforce, cold-start/CMU): https://aws.amazon.com/blogs/machine-learning/how-amazon-bedrock-custom-model-import-streamlined-llm-deployment-for-salesforce/
- Google — Colab pricing: https://cloud.google.com/colab/pricing
- vLLM — structured/guided decoding: https://docs.vllm.ai/en/latest/features/structured_outputs.html
```
