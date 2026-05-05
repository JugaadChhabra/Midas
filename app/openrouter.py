import httpx
import json
from json_repair import repair_json
from app.config import settings


def chat_json(prompt: str, model: str | None = None, system: str | None = None,
              image_urls: list[str] | None = None) -> dict:
    model = model or settings.AUDIT_MODEL
    """Call OpenRouter with response_format=json_object and parse the result.
    If image_urls is provided, the user message becomes multi-part (vision)."""
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    if image_urls:
        parts = [{"type": "text", "text": prompt}]
        for url in image_urls:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": prompt})

    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Midas",
        },
        json={
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter {r.status_code} for model {model}: {r.text}")
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"OpenRouter unexpected response: {data}")
    content = data["choices"][0]["message"]["content"]
    # Some models wrap JSON in ```json fences when response_format isn't honored
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").lstrip("json").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Gemini sometimes emits unescaped quotes/newlines inside string values.
        # json_repair best-efforts a fix; if it still fails, raise with the raw content.
        repaired = repair_json(content)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Model returned unparseable JSON: {e}\n---\n{content[:2000]}")
