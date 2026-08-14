import httpx
import json
from json_repair import repair_json
from app.config import settings

EMBED_MODEL = "google/gemini-embedding-2-preview"


def _extract_json_object(content: str) -> str:
    """The outermost {...} span, or `content` unchanged if there isn't one.

    `response_format={"type":"json_object"}` is a request, not a guarantee, and the
    `:online` web-search variants ignore it: a live probe of
    claude-opus-5:online returned a spoken preamble, then a ```json fence, then
    the object, then more prose after it. Checking `startswith("```")` misses that
    shape, so the parse used to fall through to json_repair and get rescued by
    luck.

    Slice to the LAST closing brace rather than the first — the audit payload nests
    comparisons/issues several levels deep, and stopping at the first `}` would
    truncate it mid-object. Returning `content` untouched when there is no object
    keeps the caller's error message quoting what the model actually said.
    """
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end <= start:
        return content
    return content[start:end + 1]


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via OpenRouter. Returns one vector per input."""
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    r = httpx.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Midas",
        },
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter embeddings {r.status_code}: {r.text}")
    data = r.json()
    items = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]


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
    # response_format is a request, not a guarantee — models wrap JSON in fences,
    # and the `:online` search variants narrate before and after the object. Take
    # the outermost {...} span rather than pattern-matching each way of missing.
    content = _extract_json_object(content.strip())
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


def chat_text(prompt: str, model: str | None = None, system: str | None = None) -> str:
    """Call OpenRouter without response_format constraint. Returns raw text content.
    Used for models that don't support json_object mode (e.g. perplexity/sonar).
    """
    model = model or settings.AUDIT_MODEL
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Midas",
        },
        json={"model": model, "messages": messages},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter {r.status_code} for model {model}: {r.text}")
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"OpenRouter unexpected response: {data}")
    return data["choices"][0]["message"]["content"].strip()
