"""QKSPARK Word Plugin MVP - 后端配置"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM API 配置（OpenAI 兼容格式）
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.ppinfra.com/v3/openai/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen/qwen-turbo")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "deepseek-ai/DeepSeek-V3.2")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
