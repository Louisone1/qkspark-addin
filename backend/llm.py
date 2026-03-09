"""LLM 客户端封装 - OpenAI 兼容接口"""
from openai import AsyncOpenAI
from config import LLM_API_KEY, LLM_BASE_URL, DEFAULT_MODEL, FALLBACK_MODEL

client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)


async def chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """调用大模型，失败自动 fallback"""
    target_model = model or DEFAULT_MODEL
    try:
        resp = await client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        if target_model != FALLBACK_MODEL:
            # 自动降级到备用模型
            resp = await client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        raise e
