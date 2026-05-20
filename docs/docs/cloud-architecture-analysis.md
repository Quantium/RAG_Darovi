---
sidebar_position: 3
title: Cloud Architecture & Cost Analysis
---

# RAG Darovi — Análisis de Arquitectura Cloud y Costos

> **Actualizado:** Mayo 2026 | **Precios:** AWS/GCP 2025-2026

---

## Stack Actual de Referencia

| Componente | Imagen | Rol |
|---|---|---|
| PostgreSQL 16 | `postgres:16-alpine` | Metadata: file_records, sync_state, drive_connection, extracted_documents |
| Redis 7 | `redis:7-alpine` | DB0: Celery broker · DB1: results · DB2: retrieval cache + conversation |
| MinIO | `minio/minio` | Buckets: raw-files, converted-texts |
| Milvus 2.4.21 | `milvusdb/milvus` | Vector DB HNSW COSINE 768-dim, colección `rag_documents` |
| Ollama (embed+chat) | `ollama/ollama:11435` | nomic-embed-text + qwen3.5:9b (~5.6 GB, KEEP_ALIVE=24h) |
| Ollama Vision | `ollama/ollama:11436` | llama3.2-vision:11b (~6.4 GB, KEEP_ALIVE=10m, concurrency=1) |
| 4 microservicios + dashboard | FastAPI/Python 3.11 | ingest-raw · extract-text · retrieval-admin · chatbot-response · dashboard-api |

**LLM providers soportados** (via `AsyncOpenAI` con `base_url` configurable):
Ollama (default), OpenAI, DeepSeek, Google Gemini (endpoint OpenAI-compatible).

---

## 1. Análisis de Costos Cloud — AWS vs GCP

### Definición de Workloads

| Tamaño | Usuarios | Docs/mes | Chat msgs/mes |
|---|---|---|---|
| **Small** | 1-5 | ~100 | ~500 |
| **Medium** | 10-50 | ~1,000 | ~5,000 |
| **Large** | 100+ | ~10,000 | ~50,000 |

### Mapping Servicios Docker → Cloud

| Local | AWS | GCP | Notas |
|---|---|---|---|
| PostgreSQL | RDS PostgreSQL | Cloud SQL PostgreSQL | — |
| Redis (3 DBs lógicas) | ElastiCache | Memorystore | ⚠ Memorystore NO soporta DBs lógicas |
| MinIO | S3 Standard | GCS | Cambio de SDK en 4 servicios |
| Milvus standalone | **Zilliz Cloud** (zero code change) | Vertex Matching Engine (rewrite) o Milvus self-managed | AWS ventaja clara |
| Ollama (12 GB VRAM) | EC2 g4dn.xlarge (16 GB T4) | GCE n1-standard-4 + T4 (15 GB) | — |
| App containers (8) | ECS Fargate / EKS | Cloud Run / GKE Autopilot | — |

---

### Tabla AWS — Opción A: Ollama Self-Hosted en GPU

```
                        SMALL          MEDIUM         LARGE
──────────────────────────────────────────────────────────────────────────
RDS PostgreSQL          $14/mo         $48/mo         $192/mo (Multi-AZ)
ElastiCache Redis       $12/mo         $25/mo         $146/mo (r6g.large)
S3 (2 buckets)          $2/mo          $5/mo          $25/mo
Zilliz Cloud            $0-65/mo       $65/mo         $130-195/mo
ECS Fargate (8 svcs)    $40/mo         $80/mo         $200/mo
GPU: g4dn.xlarge        $379/mo OD     $228/mo 1yr    $380/mo 1yr g5.xlarge
     (spot ~$115/mo)
ALB + NAT Gateway       $48/mo         $57/mo         $105/mo
Data transfer           $5/mo          $8/mo          $45/mo
──────────────────────────────────────────────────────────────────────────
TOTAL (on-demand GPU)   ~$570/mo       ~$516/mo       ~$1,340/mo
TOTAL (spot GPU)        ~$305/mo       —              —
TOTAL (Reserved 1yr)    ~$390/mo       ~$496/mo       ~$1,300/mo
```

### Tabla GCP — Opción A: Ollama Self-Hosted en GPU

```
                        SMALL          MEDIUM         LARGE
──────────────────────────────────────────────────────────────────────────
Cloud SQL PostgreSQL    $25/mo         $80/mo         $200/mo (HA)
Memorystore Redis       $30/mo         $85/mo         $175/mo (Standard HA)
GCS                     $1/mo          $4/mo          $18/mo
Vertex Matching Engine  $65-80/mo      $80-130/mo     $160-240/mo
Cloud Run / GKE         $20/mo         $90/mo         $200/mo
GCE GPU n1+T4           $388/mo OD     $280/mo 1yr    $600/mo a2-highgpu 1yr
                        (preempt ~$110)
Cloud LB + NAT          $28/mo         $52/mo         $95/mo
──────────────────────────────────────────────────────────────────────────
TOTAL (on-demand GPU)   ~$557/mo       ~$771/mo       ~$1,428/mo
TOTAL (preemptible)     ~$279/mo       —              —
TOTAL (1yr committed)   ~$449/mo       ~$691/mo       ~$1,428/mo
```

### Opción B: API-Based LLM (sin GPU)

```
                        SMALL          MEDIUM         LARGE
──────────────────────────────────────────────────────────────────────────
AWS infra sin GPU       ~$170/mo       ~$250/mo       ~$600/mo
GCP infra sin GPU       ~$165/mo       ~$270/mo       ~$620/mo
```

---

## 2. Arquitectura de Despliegue de Contenedores

### AWS — ECS Fargate + EC2 GPU (Recomendado Small/Medium)

```
┌──────────────────────────────────────────────────────────────────────┐
│  AWS Region (us-east-1) · VPC 10.0.0.0/16                           │
│                                                                      │
│  Public Subnets              Private Subnets                         │
│  ┌──────────────┐            ┌────────────────────────────────────┐  │
│  │ ALB          │───────────▶│ ECS Fargate Cluster                │  │
│  │ 80/443 HTTPS │            │ dashboard-api :8000                      │  │
│  └──────────────┘            │ chatbot-response :8020             │  │
│  ┌──────────────┐            │ retrieval-admin :8010              │  │
│  │ NAT Gateway  │            │ ingest-raw :8030                   │  │
│  └──────────────┘            │ extract-text :8031                 │  │
│         │                    │ dashboard-worker (x2) · dashboard-beat         │  │
│         │                    └────────────────────────────────────┘  │
│         │                    ┌────────────────────────────────────┐  │
│         └───────────────────▶│ EC2 g4dn.xlarge (16 GB T4)        │  │
│                              │ ollama :11434  (embed+chat)        │  │
│                              │ ollama-vision :11435 (VLM)         │  │
│                              │ EBS gp3 30 GB → /root/.ollama      │  │
│                              └────────────────────────────────────┘  │
│                              ┌────────────────────────────────────┐  │
│                              │ RDS PostgreSQL (db.t3.medium)      │  │
│                              │ ElastiCache Redis (t3.micro)       │  │
│                              │ S3: raw-files · converted-texts    │  │
│                              │ Zilliz Cloud (VPC peering opt.)    │  │
│                              └────────────────────────────────────┘  │
│  ECR: dashboard-core · ingest-raw · extract-text ·                   │
│       retrieval-admin · chatbot-response                             │
│  Secrets Manager: DATABASE_URL · REDIS_URL · LLM_API_KEY · ...      │
└──────────────────────────────────────────────────────────────────────┘
```

**Large workload → EKS con 3 node groups:**
```
EKS Cluster
├── Node Group: system   t3.medium ×2  — kube-system + ingress
├── Node Group: app      t3.large ×2-4 (autoscaling) — CPU containers
└── Node Group: gpu      g4dn.xlarge ×1-2
    ├── Taint: nvidia.com/gpu=true:NoSchedule
    ├── Ollama + ollama-vision + dashboard-worker-vision
    └── EBS gp3 PersistentVolume → /root/.ollama
```

---

### GCP — GKE Autopilot + GCE GPU VM

```
┌──────────────────────────────────────────────────────────────────────┐
│  GCP Project / VPC Network                                           │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ GKE Autopilot Cluster                                       │     │
│  │ Deployments: dashboard-api · retrieval-admin · chatbot-response   │     │
│  │              ingest-raw · extract-text                      │     │
│  │ StatefulSet:  dashboard-worker (×2) · dashboard-beat                    │     │
│  │ CronJob:      ingest-raw-cron  "0 * * * *"                  │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ GCE VM: n1-standard-4 + nvidia-tesla-t4                    │     │
│  │ Docker: ollama · ollama-vision · dashboard-worker-vision          │     │
│  │ Persistent Disk 50 GB → /root/.ollama                       │     │
│  │ IP interna expuesta a GKE via VPC (sin load balancer)       │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  Cloud SQL PostgreSQL  · Memorystore Redis (key prefixes)            │
│  GCS: raw-files · converted-texts                                    │
│  Milvus self-managed en GCE (opción más simple, zero code change)    │
│  Artifact Registry: 5 repos · Secret Manager: producción vars        │
└──────────────────────────────────────────────────────────────────────┘
```

> **⚠ Trampa GCP:** Memorystore no soporta múltiples DBs lógicas (DB 0/1/2).
> Requiere refactorizar Celery config en `dashboard/rag-dashboard-core` para usar key prefixes,
> o pagar 3 instancias separadas (~$90/mo extra).

---

## 3. Plan DevOps — GitHub Actions

### Estructura CI/CD Multi-Repo

```
Pipeline 1: CI por servicio   (en cada sub-repo)
  on: push/PR a main · develop
  jobs: test (pytest) → build → push a ECR / Artifact Registry

Pipeline 2: Deploy orquestador  (en RAG_Darovi)
  on: push a main · workflow_dispatch (staging / production)
  jobs: update-submodules → deploy → smoke tests

Pipeline 3: Infrastructure      (Terraform)
  on: cambios en terraform/
  jobs: plan → apply (aprobación manual para prod)
```

### Pipeline 1 — CI por Servicio

```yaml
# .github/workflows/ci.yml (en cada service repo)
name: CI
on:
  push: { branches: [main, develop] }
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { submodules: recursive }
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: "pip" }
      - run: pip install -r requirements-dev.txt && pytest --tb=short -q

  build-and-push:
    needs: test
    if: github.ref == 'refs/heads/main'
    permissions: { id-token: write, contents: read }
    steps:
      - uses: actions/checkout@v4
      # AWS: configure-aws-credentials (OIDC) + ECR login
      # GCP: google-github-actions/auth + Artifact Registry login
      - run: |
          docker build -t $REGISTRY/$IMAGE:${{ github.sha }} .
          docker push $REGISTRY/$IMAGE:${{ github.sha }}
          docker tag $REGISTRY/$IMAGE:${{ github.sha }} $REGISTRY/$IMAGE:latest
          docker push $REGISTRY/$IMAGE:latest
```

### Pipeline 2 — Deploy Orquestador

```yaml
# .github/workflows/deploy.yml (en RAG_Darovi)
name: Deploy
on:
  push: { branches: [main] }
  workflow_dispatch:
    inputs:
      environment: { type: choice, options: [staging, production] }
jobs:
  deploy:
    environment: ${{ inputs.environment || 'staging' }}
    steps:
      - uses: actions/checkout@v4
        with: { submodules: recursive, token: ${{ secrets.GH_PAT }} }
      - run: git submodule update --remote --merge
      # AWS: aws ecs update-service --force-new-deployment (×8 servicios)
      # GCP: kubectl rollout restart deployment/dashboard-api ...
      - name: Smoke tests
        run: |
          curl -fsS https://$DOMAIN/status
          curl -fsS https://$DOMAIN:8010/health
          curl -fsS https://$DOMAIN:8020/health
```

### Estructura Terraform

```
terraform/
├── modules/
│   ├── networking/      VPC · subnets · NAT · security groups
│   ├── database/        RDS/Cloud SQL + ElastiCache/Memorystore
│   ├── storage/         S3/GCS buckets con lifecycle policies
│   ├── vector-db/       Zilliz data source  o  Milvus en EC2/GCE
│   ├── gpu-instance/    EC2 g4dn.xlarge / GCE n1+T4, user_data Ollama
│   ├── app-cluster/     ECS Fargate / GKE Autopilot
│   └── secrets/         AWS Secrets Manager / GCP Secret Manager
├── environments/
│   ├── staging/         main.tf + terraform.tfvars
│   └── production/      main.tf + terraform.tfvars
└── providers.tf
```

El `user_data` del GPU instance reutiliza `scripts/ollama-docker-entrypoint.sh` (ya existente):
monta EBS/Persistent Disk en `/root/.ollama` y espera `/tmp/ollama-models-ready`.

### Mapeo de Secrets

| AWS Secrets Manager path | Variables de entorno |
|---|---|
| `rag-darovi/database-url` | `DATABASE_URL`, `DATABASE_URL_SYNC` |
| `rag-darovi/redis-url` | `REDIS_BROKER_URL`, `REDIS_RESULT_URL`, `REDIS_CACHE_URL` |
| `rag-darovi/minio-credentials` | Sustituido por IAM role para S3 (creds eliminados) |
| `rag-darovi/llm-api-key` | `LLM_API_KEY`, `DEEPSEEK_API_KEY` |
| `rag-darovi/google-oauth` | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` |
| `rag-darovi/token-encryption` | `TOKEN_ENCRYPTION_KEY` |
| `rag-darovi/api-key` | `API_KEY` |

### Rollback

```bash
# Git
git checkout v0.8.0 && git submodule update --init --recursive

# AWS ECS
aws ecs update-service --task-definition rag-api:PREVIOUS_REVISION

# GKE
kubectl rollout undo deployment/dashboard-api
```

Blue/Green: ECS `maximumPercent=200, minimumHealthyPercent=100` (la tarea vieja vive hasta que la nueva pasa health check).

---

## 4. Mantenibilidad: AWS vs GCP

| Criterio | AWS | GCP | Ganador |
|---|---|---|---|
| **Vector DB managed** | Zilliz Cloud (zero code change, pymilvus idéntico) | Vertex Matching Engine (rewrite SDK) o self-managed | **AWS** |
| **Redis multi-DB** | ElastiCache soporta DBs lógicas 0/1/2 | Memorystore NO soporta (breaking change) | **AWS** |
| **DX / Tooling** | ECS Copilot CLI, ECS Exec para debug | Cloud Run simple, GKE maduro | Empate |
| **Multi-región** | RDS Multi-AZ + Read Replica; S3 CRR | Cloud SQL replicas; GCS multi-region nativo | **GCP** |
| **Observabilidad** | CloudWatch Container Insights ($0.50/GB logs) | Cloud Logging: más barato, JSON structurado nativo | **GCP** |
| **Secret management** | Secrets Manager integrado con ECS/EKS | Secret Manager integrado con GKE | Empate |

> **Veredicto: AWS gana en mantenibilidad** por compatibilidad directa con Zilliz Cloud + ElastiCache sin cambios de código.

---

## 5. Reliability: AWS vs GCP

| Servicio | AWS SLA | GCP SLA | Notas |
|---|---|---|---|
| PostgreSQL | RDS Multi-AZ: 99.95% | Cloud SQL HA: 99.95% | Igual |
| Redis | ElastiCache Cluster: 99.99% | Memorystore Basic: 99.9% | AWS Cluster superior |
| Object Storage | S3: 99.99% (11 9s) | GCS: 99.99% (11 9s) | Igual |
| Containers | ECS: 99.99% · EKS: 99.9% | Cloud Run: 99.95% · GKE: 99.95% | ECS leve ventaja |
| GPU Instances | Sin SLA (best-effort) | Sin SLA (best-effort) | Igual |

**Consideración crítica — Cold start de Ollama:**

El `KEEP_ALIVE=24h` implica que un reinicio del GPU instance requiere re-descargar 12 GB de modelos (start_period actual: 7200s embed, 14400s vision = hasta 4h de indisponibilidad).

**Mitigación:** EBS gp3 30 GB persistente para `/root/.ollama` → modelos sobreviven restart del container. Usar **Reserved Instance** (no spot) para el GPU node.

**Auto-scaling GPU:** Celery ya implementa el throttling correcto (embed concurrency=4, vision=1). Para Large: 2 GPU instances con Celery routing a Ollama endpoints específicos; vision permanece en 1 instancia.

---

## 6. Costos de APIs de LLM

### Supuestos (del codebase)

- Embedding por doc: 2,000 tokens · `EMBED_BATCH_SIZE=64`
- Chat query: 1,000 tokens input + 500 tokens output

### Costo por 1,000 Documentos (embedding)

| Provider | Modelo | $/1K docs |
|---|---|---|
| OpenAI | text-embedding-3-small ($0.02/M) | **$0.04** |
| OpenAI | text-embedding-3-large ($0.13/M) | $0.26 |
| Google | text-embedding-004 ($0.025/M) | **$0.05** |
| AWS Bedrock | Titan Text Embeddings ($0.10/M) | $0.20 |
| Ollama local | nomic-embed-text | **$0** (solo compute) |

### Costo por 1,000 Chat Messages

| Provider | Modelo | Input $/M | Output $/M | **$/1K msgs** |
|---|---|---|---|---|
| OpenAI | GPT-4o | $5.00 | $15.00 | **$12.50** |
| OpenAI | GPT-4o-mini | $0.15 | $0.60 | **$0.45** |
| Anthropic | Claude Sonnet 4.6 | $3.00 | $15.00 | **$10.50** |
| Anthropic | Claude Haiku 4.5 | $0.80 | $4.00 | **$2.80** |
| DeepSeek | deepseek-chat | $0.27 | $1.10 | **$0.82** |
| DeepSeek | deepseek-reasoner | $0.55 | $2.19 | **$1.65** |
| Google | Gemini 2.0 Flash | $0.10 | $0.40 | **$0.30** |
| Google | Gemini 1.5 Flash | $0.075 | $0.30 | **$0.225** |
| AWS Bedrock | Claude Sonnet 4.6 | ~$3.30 | ~$16.50 | **~$11.55** |
| Vertex AI | Gemini via Vertex | $0.10 | $0.40 | **$0.30** |
| Ollama local | qwen3.5:9b | — | — | **$0** |

### Costo Mensual de APIs por Workload

| Provider / Modelo | Small (100d · 500 msgs) | Medium (1K d · 5K msgs) | Large (10K d · 50K msgs) |
|---|---|---|---|
| GPT-4o | $6.25/mo | $62.54/mo | $625.40/mo |
| GPT-4o-mini | $0.23/mo | $2.29/mo | $22.90/mo |
| Claude Sonnet 4.6 | $5.25/mo | $52.54/mo | $525.40/mo |
| Claude Haiku 4.5 | $1.40/mo | $14.04/mo | $140.40/mo |
| **DeepSeek Chat** | **$0.41/mo** | **$4.14/mo** | **$41.40/mo** |
| **Gemini 2.0 Flash** | **$0.16/mo** | **$1.55/mo** | **$15.50/mo** |
| Ollama local | $0/mo | $0/mo | $0/mo |

---

## 7. Comparativa API vs Despliegue en Cloud

### Break-Even: ¿Cuándo conviene self-hosted GPU?

**Costo fijo GPU** (AWS g4dn.xlarge 1yr Reserved): **$228/mo** — cubre inferencia ilimitada.

| Provider | $/msg | Msgs/mes para break-even |
|---|---|---|
| GPT-4o | $0.01250 | ~18,240 msgs |
| Claude Sonnet 4.6 | $0.01050 | ~21,714 msgs |
| Claude Haiku 4.5 | $0.00280 | ~81,429 msgs |
| DeepSeek Chat | $0.00082 | ~278,049 msgs |
| Gemini 2.0 Flash | $0.00030 | ~760,000 msgs |

### Análisis Híbrido: Embeddings Locales + Chat API

```
CPU instance m5.xlarge para Ollama embed únicamente ($140/mo)
  — nomic-embed-text no requiere GPU, funciona en CPU a batch=64

Híbrido Medium:
  CPU instance (embed)         $140/mo
  Infra (RDS+Redis+S3+Zilliz)  $200/mo
  DeepSeek Chat API (5K msgs)  $4.10/mo
  TOTAL                        ~$344/mo

Pure API Medium:
  Infra sin GPU                $250/mo
  DeepSeek Chat API (5K msgs)  $4.10/mo
  TOTAL                        ~$254/mo

Conclusión: Para small/medium, Pure API es más económico.
El híbrido solo conviene a partir de ~50K mensajes/mes.
```

---

## 8. Recomendaciones — Matriz Calidad vs Costo (2×2)

```
                    BAJO COSTO                      ALTO COSTO
              ┌───────────────────────────────────────────────────┐
  ALTA        │  ② SMART STARTUP ✓ (Óptimo)  │  ④ ENTERPRISE    │
  CALIDAD     │  AWS ECS + Gemini 2.0 Flash  │  AWS EKS +        │
              │  + spot g4dn (solo embed)    │  Bedrock Claude   │
              ├───────────────────────────────────────────────────┤
  BAJA        │  ① MVP / POC                 │  ③ EVITAR         │
  CALIDAD     │  GCP Cloud Run +             │  EKS oversized +  │
              │  DeepSeek Chat API           │  LLM mid-tier     │
              └───────────────────────────────────────────────────┘
```

---

### ① MVP / POC — Bajo Costo · Calidad Media

**Stack: GCP Cloud Run + DeepSeek Chat + text-embedding-3-small**

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1/
LLM_MODEL=deepseek-chat
LLM_API_KEY=<key>
EMBED_MODEL=text-embedding-3-small
# Ollama containers eliminados — zero cambios de código
```

| | Small | Medium |
|---|---|---|
| **Costo total** | ~$85-105/mo | ~$280-330/mo |

**Trade-offs:**
- DeepSeek calidad ~70-80% vs GPT-4o para tareas RAG
- Cold starts en Cloud Run (1-3s) afectan UX de chat en tiempo real
- Sin GPU → vision pipeline usa Tesseract fallback (ya implementado)
- DeepSeek: proveedor con outages ocasionales

**Cuándo elegirlo:** PoC, herramienta interna, pre-revenue, budget < $200/mo

---

### ② SMART STARTUP — Bajo-Medio Costo · Alta Calidad ✓ Recomendado

**Stack: AWS ECS Fargate + Gemini 2.0 Flash + spot g4dn.xlarge (solo embed)**

```env
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=<google-api-key>
EMBED_MODEL=nomic-embed-text          # Mantiene índice HNSW 768-dim sin cambios
OLLAMA_BASE_URL=http://<gpu-ec2>:11434  # Solo para embeddings
```

| | Small | Medium |
|---|---|---|
| **Costo total** | ~$320/mo | ~$450/mo |

**Trade-offs:**
- Spot instance puede interrumpirse (mitigado con EBS persistente, restart ~5-10min)
- Gemini 2.0 Flash calidad comparable a GPT-4o en RAG, a 30× menos costo de chat
- Zilliz Cloud = zero cambios en `retrieval_admin/app/retrieval.py` (pymilvus idéntico)

**Cuándo elegirlo:** Producción startup, 10-100 usuarios activos, team con expertise Python/FastAPI pero sin experiencia Kubernetes profunda

---

### ③ EVITAR — Alto Costo · Calidad Media

**Patrón a evitar:** EKS overprovisioned + modelo open-source mid-tier en GPU oversized

Ejemplo concreto:
- g5.2xlarge ($1.21/hr = **$871/mo**) ejecutando Llama 3 (calidad inferior a Gemini Flash)
- EKS control plane ($73/mo) para workload small/medium
- Milvus + Redis self-managed (alta carga ops)
- Resultado: **$1,500-2,000/mo** por calidad equivalente al Cuadrante ②

---

### ④ ENTERPRISE — Alto Costo · Alta Calidad

**Stack: AWS EKS + Bedrock Claude Sonnet 4.6 + Ollama GPU + RDS Multi-AZ + Zilliz Enterprise**

> **⚠ Nota de código:** Bedrock usa `boto3` Bedrock Runtime, NO `AsyncOpenAI`.
> Requiere cambio en `chatbot_response/app/llm.py` y `legacy/src/generator/`.
> Evaluar si el Converse API proxy elimina este cambio antes de implementar.

| | Medium | Large |
|---|---|---|
| **Costo total** | ~$800-1,000/mo | ~$1,600-2,000/mo |

**Trade-offs:**
- Data residency US/EU (compliance HIPAA, SOC2, GDPR)
- SLA y billing unificado en AWS
- WAF + Shield Standard incluido
- Claude: mejor calidad para documentos complejos y reasoning legal/financiero

**Cuándo elegirlo:** Healthcare, legal, finanzas con requisitos de residencia de datos; contratos enterprise con SLA; equipo > 15 personas; > 100 DAU

---

## 9. Recomendación Principal para RAG Darovi

**Para los próximos 12 meses: Cuadrante ② en AWS**

| Razón | Detalle |
|---|---|
| Zilliz Cloud | Zero cambios en `retrieval_admin/app/retrieval.py` (pymilvus idéntico) |
| ElastiCache | Soporta DBs lógicas 0/1/2 (sin refactor de Celery config) |
| g4dn.xlarge spot + EBS | Embeddings locales de calidad, costo controlado |
| Gemini 2.0 Flash | Mejor ratio calidad/costo 2025/2026 para LLM chat |
| ECS Fargate | Más simple que GKE para equipo sin expertise Kubernetes profundo |

### Roadmap de Implementación

```
MES 1 — API keys + staging
  ✓ GitHub Actions CI en cada sub-repo
  ✓ Terraform: VPC + RDS + ElastiCache + S3 + ECS Fargate (sin GPU)
  ✓ Migrar MinIO → S3 en settings.py de los 4 servicios (SDK + IAM role)
  ✓ Deploy staging con DeepSeek o Gemini Flash

MES 2 — Producción + GPU
  ✓ Agregar g4dn.xlarge al Terraform (EBS gp3 30 GB)
  ✓ Migrar Milvus → Zilliz Cloud (export/import vectors)
  ✓ Secrets Manager para todos los secrets de production.env.example
  ✓ Pipeline de deploy en repo orquestador

MES 3 — Observabilidad + optimización
  ✓ CloudWatch Container Insights (RDS, Redis, ECS CPU)
  ✓ Cost allocation tags en todos los recursos
  ✓ Compra Reserved Instance GPU ($379 → $228/mo)
  ✓ Evaluar EventBridge Scheduler vs Celery beat para ingest_raw cron
```
