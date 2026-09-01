# 示例 1：AWQ INT4 量化模型启动
python -m vllm.entrypoints.openai.api_server `
  --model "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B-AWQ" `
  --served-model-name "DeepSeek-R1-Distill-Qwen-32B-AWQ" `
  --dtype "float16" `
  --quantization "awq" `
  --max-model-len 4096 `
  --gpu-memory-utilization 0.92 `
  --tensor-parallel-size 1 `
  --port 8000

# 示例 2：GPTQ INT4 量化模型启动
python -m vllm.entrypoints.openai.api_server \
  --model "/home/brian/llm/Qwen/Qwen2.5-1.5B-Instruct-GPTQ-Int4" \
  --served-model-name "Qwen2.5-1.5B-GPTQ-Int4" \
  --host 0.0.0.0\
  --dtype "float16" \
  --quantization "gptq" \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.92 \
  --tensor-parallel-size 1 \
  --port 8000

# FP16 基线模式
python -m vllm.entrypoints.openai.api_server \
  --model "/home/brian/llm/Qwen/Qwen2.5-1.5B-Instruct" \
  --served-model-name "Qwen2.5-1.5B" \
  --host 0.0.0.0\
  --dtype "float16" \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.92 \
  --tensor-parallel-size 1 \
  --port 8000
