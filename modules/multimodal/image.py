"""
BEA MAX — Multimodal Image Module
Provider chain: OpenAI DALL-E 3 → HuggingFace Stable Diffusion → stub
Vision: GPT-4o for image description/analysis.

All imports are lazy; works with zero API keys (returns stubs).
"""
from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Result types ──────────────────────────────────────────────

@dataclass
class ImageResult:
    url:       Optional[str]   = None
    base64:    Optional[str]   = None   # raw bytes as b64 string
    provider:  str             = "stub"
    cost_usd:  float           = 0.0
    prompt:    str             = ""
    error:     Optional[str]   = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.url or self.base64)


# ── Cost table (USD) ──────────────────────────────────────────
_DALLE_COSTS: dict[str, dict[str, float]] = {
    "1024x1024": {"standard": 0.040, "hd": 0.080},
    "1792x1024": {"standard": 0.080, "hd": 0.120},
    "1024x1792": {"standard": 0.080, "hd": 0.120},
}


# ── Provider: OpenAI DALL-E 3 ─────────────────────────────────

async def _dalle3(prompt: str, size: str, quality: str) -> ImageResult:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=api_key)
        resp = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,       # type: ignore[arg-type]
            quality=quality, # type: ignore[arg-type]
            n=1,
            response_format="url",
        )
        url  = resp.data[0].url
        cost = _DALLE_COSTS.get(size, {}).get(quality, 0.04)
        log.info("dalle3_generated", size=size, quality=quality, cost=cost)
        return ImageResult(url=url, provider="dalle3", cost_usd=cost, prompt=prompt)
    except Exception as e:
        raise RuntimeError(f"DALL-E 3 failed: {e}") from e


# ── Provider: HuggingFace Inference API (Stable Diffusion) ────

async def _huggingface_sd(prompt: str, size: str) -> ImageResult:
    hf_token = os.getenv("HUGGINGFACE_API_TOKEN", "") or os.getenv("HF_TOKEN", "")
    if not hf_token:
        raise RuntimeError("HUGGINGFACE_API_TOKEN not set")

    model_id = os.getenv(
        "HF_IMAGE_MODEL",
        "stabilityai/stable-diffusion-xl-base-1.0",
    )
    url = f"https://api-inference.huggingface.co/models/{model_id}"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {hf_token}"},
                json={"inputs": prompt},
            )
            resp.raise_for_status()
            b64 = base64.b64encode(resp.content).decode()
            log.info("huggingface_sd_generated", model=model_id)
            return ImageResult(base64=b64, provider="huggingface_sd", cost_usd=0.0, prompt=prompt)
    except Exception as e:
        raise RuntimeError(f"HuggingFace SD failed: {e}") from e


# ── Provider: stub ────────────────────────────────────────────

def _stub_image(prompt: str) -> ImageResult:
    log.warning("image_stub_used", prompt=prompt[:80])
    return ImageResult(
        url=None,
        base64=None,
        provider="stub",
        cost_usd=0.0,
        prompt=prompt,
        error="No image provider available (set OPENAI_API_KEY or HUGGINGFACE_API_TOKEN)",
    )


# ── Public: generate_image ────────────────────────────────────

async def generate_image(
    prompt:   str,
    size:     str = "1024x1024",
    quality:  str = "standard",
    provider: str = "auto",
) -> ImageResult:
    """
    Generate an image from a text prompt.
    provider: "auto" | "dalle3" | "huggingface" | "stub"
    Returns ImageResult; never raises — falls back to stub.
    """
    if provider in ("dalle3", "auto"):
        try:
            return await _dalle3(prompt, size, quality)
        except Exception as e:
            log.debug("dalle3_unavailable", err=str(e)[:80])
            if provider == "dalle3":
                return ImageResult(prompt=prompt, provider="dalle3", error=str(e))

    if provider in ("huggingface", "auto"):
        try:
            return await _huggingface_sd(prompt, size)
        except Exception as e:
            log.debug("huggingface_sd_unavailable", err=str(e)[:80])
            if provider == "huggingface":
                return ImageResult(prompt=prompt, provider="huggingface", error=str(e))

    return _stub_image(prompt)


# ── Public: describe_image ────────────────────────────────────

async def describe_image(
    image_url_or_base64: str,
    question: str = "Describe this image in detail.",
) -> str:
    """
    Analyze / describe an image using GPT-4o Vision.
    Accepts a URL or a base64-encoded image string.
    Returns a text description, or an error string if unavailable.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "[Vision unavailable: OPENAI_API_KEY not set]"

    # Determine content type
    if image_url_or_base64.startswith("http://") or image_url_or_base64.startswith("https://"):
        image_content: dict = {"type": "image_url", "image_url": {"url": image_url_or_base64}}
    else:
        # Assume raw base64; detect media type naively
        if image_url_or_base64.startswith("/9j/"):
            mime = "image/jpeg"
        elif image_url_or_base64.startswith("iVBOR"):
            mime = "image/png"
        else:
            mime = "image/png"
        data_uri = f"data:{mime};base64,{image_url_or_base64}"
        image_content = {"type": "image_url", "image_url": {"url": data_uri}}

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    image_content,
                ],
            }],
            max_tokens=1024,
        )
        description = resp.choices[0].message.content or ""
        log.info("image_described", chars=len(description))
        return description
    except Exception as e:
        log.error("describe_image_failed", err=str(e)[:120])
        return f"[Vision error: {e}]"


# ── Public: generate_image (simple HF path, returns file path) ──

async def generate_image_hf(prompt: str) -> Optional[str]:
    """
    Generate an image using HuggingFace Inference API (SDXL).
    Saves result to workspace/images/{uuid}.png and returns the path.
    Falls back to None with a warning if HF API key is missing or call fails.
    """
    try:
        from config.settings import get_settings
        settings = get_settings()
        hf_key = getattr(settings, "huggingface_api_key", "") or os.getenv("HUGGINGFACE_API_KEY", "")
    except Exception:
        hf_key = os.getenv("HUGGINGFACE_API_KEY", "")

    log.info("generate_image_hf_called", prompt=prompt[:80], has_key=bool(hf_key))

    if not hf_key:
        log.warning("generate_image_hf_no_key", prompt=prompt[:80])
        return None

    model_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                model_url,
                headers={"Authorization": f"Bearer {hf_key}"},
                json={"inputs": prompt},
            )
            resp.raise_for_status()
            image_bytes = resp.content

        # Resolve workspace/images dir
        try:
            from config.settings import get_settings
            workspace = Path(get_settings().workspace_dir)
        except Exception:
            workspace = Path("workspace")

        images_dir = workspace / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image_path = images_dir / f"{uuid.uuid4()}.png"
        image_path.write_bytes(image_bytes)

        log.info("generate_image_hf_saved", path=str(image_path))
        return str(image_path)

    except Exception as exc:
        log.warning("generate_image_hf_failed", err=str(exc)[:120])
        return None


# ── Capability probe ──────────────────────────────────────────

def image_capabilities() -> dict:
    """Returns which image providers are currently available.

    Checks actual capability, not just key existence.
    OpenRouter keys (sk-or-*) cannot call DALL-E or Vision directly.
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    # OpenRouter keys start with sk-or- and cannot do DALL-E/Vision
    is_real_openai = bool(openai_key) and not openai_key.startswith("sk-or-")
    return {
        "dalle3":       is_real_openai,
        "huggingface":  bool(os.getenv("HUGGINGFACE_API_TOKEN") or os.getenv("HF_TOKEN")),
        "vision_gpt4o": is_real_openai,
        "stub":         True,
    }
