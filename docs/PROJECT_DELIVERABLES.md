# Project Deliverables (Five Stages)

## Stage 1: System Architecture and Modules
1. Data flow:
   - User request enters `/v1/ask`
   - Intent router decides `literature`, `clinical`, or `both`
   - Branch retrieval performs hybrid recall
   - Reranker refines candidates
   - LLM generates structured answer
   - Guardrail appends safety boundary
2. LangGraph routing:
   - Nodes: `route_intent -> retrieve_* -> generate_answer -> post_guard`
   - Conditional edges route by intent

## Stage 2: Core Pipeline Logic
1. Data processing:
   - `app/retrieval/mineru_pipeline.py`
   - `app/retrieval/chunking.py` (parent-child chunking)
2. Hybrid retrieval:
   - `app/retrieval/embeddings.py`
   - `app/retrieval/vector_store.py`
   - `app/retrieval/retriever.py`
3. Workflow scheduling:
   - `app/workflow.py` with `StateGraph` + conditional branching

## Stage 3: Model Deployment and Performance
1. vLLM startup commands:
   - `scripts/vllm_start_commands.ps1` (AWQ/GPTQ INT4 examples)
2. VRAM optimization knobs:
   - `--quantization`
   - `--max-model-len`
   - `--gpu-memory-utilization`
   - `--tensor-parallel-size`
3. Prompt strategy:
   - Structured output template + internal reasoning policy in `app/prompts.py`

## Stage 4: Testing and Evaluation
1. Deterministic lexical compatibility diagnostic:
   - `POST /v1/eval/ragas` is a legacy compatibility URL only; Ragas is neither installed nor run.
   - Current metadata: `backend=deterministic_lexical`, `metric_version=token_overlap_v1`, and `aggregation=macro_average`.
   - Per sample, only `ground_truth` and `retrieved_contexts` are compared. The compatibility field `context_precision` is a context-hit ratio, while `context_recall` is ground-truth token coverage; sample values are macro-averaged.
   - `response` is ignored. These fields do not represent Ragas, faithfulness, answer factual correctness, clinical safety, or clinical effectiveness.
2. LLM-as-a-Judge:
   - JSON scoring template in `app/prompts.py`
   - Execution wrapper in `app/llm/llm_judge.py`
   - This is a separate path and must not be conflated with the deterministic lexical compatibility diagnostic.

## Stage 5: Resume and Interview Prep
1. Evidence-bounded STAR bullets (samples):
   - Built a LangGraph-based intent routing system that separates literature retrieval from clinical follow-up matching.
   - Implemented a BGE-M3-style hybrid retrieval and reranking pipeline; report quality or latency improvements only with independently reproducible measurements.
   - Prepared vLLM INT4 deployment commands for a 32B-class model under single-GPU memory constraints; do not present deployment targets as measured results.
   - Exposed a deterministic token-overlap diagnostic for ground-truth/context comparison through a legacy-compatible URL, with explicit backend, metric-version, aggregation, and non-clinical limitations.
2. High-frequency interview deep-dive questions:
   - Why parent-child chunking for medical corpora?
   - How to tune dense/sparse weighting in hybrid retrieval?
   - How to reduce risk from intent misrouting in agent workflows?
