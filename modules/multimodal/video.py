"""
JARVIS MAX — Multimodal Video Module
- generate_video_stub: placeholder (real gen too expensive; interface ready)
- extract_video_frames: OpenCV primary, PIL fallback
- analyze_video: sampled frames → GPT-4o Vision

All imports are lazy; works with zero API keys and without cv2/PIL.
"""
from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import structlog

log = structlog.get_logger(__name__)


# ── Result types ──────────────────────────────────────────────

@dataclass
class VideoStubResult:
    prompt:    str
    duration_s: int
    provider:  str  = "stub"
    message:   str  = ""
    url:       Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.provider != "error"


@dataclass
class FrameResult:
    frames:     list[bytes]        = field(default_factory=list)  # raw JPEG bytes per frame
    timestamps: list[float]        = field(default_factory=list)  # seconds
    provider:   str                = "stub"
    error:      Optional[str]      = None
    frame_count: int               = 0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.frames)


@dataclass
class VideoAnalysisResult:
    description:  str
    frame_count:  int           = 0
    sampled:      int           = 0
    provider:     str           = "stub"
    error:        Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ── Public: generate_video_stub ───────────────────────────────

async def generate_video_stub(
    prompt:     str,
    duration_s: int = 5,
) -> VideoStubResult:
    """
    Stub for video generation.
    Real providers (Runway ML, Pika, Sora) are not yet integrated due to cost.
    Interface is production-ready for future wiring.
    """
    log.info("video_generate_stub", prompt=prompt[:80], duration_s=duration_s)
    return VideoStubResult(
        prompt=prompt,
        duration_s=duration_s,
        provider="stub",
        message=(
            f"Video generation stub — {duration_s}s clip for: '{prompt[:60]}'. "
            "Real generation requires Runway ML / Pika / Sora API keys. "
            "Set RUNWAY_API_KEY, PIKA_API_KEY, or OPENAI_SORA_KEY to enable."
        ),
        url=None,
    )


# ── Frame extraction: OpenCV ──────────────────────────────────

def _extract_frames_cv2(video_path: str, fps: float) -> FrameResult:
    try:
        import cv2  # type: ignore
    except ImportError:
        raise RuntimeError("cv2 not installed (pip install opencv-python-headless)")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    video_fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_skip  = max(1, int(video_fps / fps))
    frames:     list[bytes] = []
    timestamps: list[float] = []
    idx         = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % frame_skip == 0:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                frames.append(buf.tobytes())
                timestamps.append(round(idx / video_fps, 2))
        idx += 1

    cap.release()
    log.info("cv2_frames_extracted", count=len(frames))
    return FrameResult(
        frames=frames,
        timestamps=timestamps,
        provider="cv2",
        frame_count=len(frames),
    )


# ── Frame extraction: PIL fallback ───────────────────────────

def _extract_frames_pil(video_path: str, fps: float) -> FrameResult:
    """
    PIL-based fallback for GIF files and single-image videos.
    For real video files without cv2 this returns an error.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        raise RuntimeError("PIL not installed (pip install Pillow)")

    path = Path(video_path)
    if path.suffix.lower() not in {".gif"}:
        raise RuntimeError("PIL frame extraction only supports GIF; install opencv for video")

    img = Image.open(video_path)
    frames:     list[bytes] = []
    timestamps: list[float] = []
    frame_dur   = 1.0 / max(fps, 0.1)

    try:
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=75)
            frames.append(buf.getvalue())
            timestamps.append(round(i * frame_dur, 2))
    except EOFError:
        _silent_log.debug("suppressed_exception", src='video.py')

    log.info("pil_frames_extracted", count=len(frames))
    return FrameResult(
        frames=frames,
        timestamps=timestamps,
        provider="pil",
        frame_count=len(frames),
    )


# ── Public: extract_video_frames ─────────────────────────────

async def extract_video_frames(
    video_path: Union[str, Path],
    fps:        float = 1.0,
) -> FrameResult:
    """
    Extract frames from a video file at the given fps rate.
    Uses OpenCV if available, falls back to PIL (GIF only).
    Never raises.
    """
    import asyncio
    path = str(video_path)

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract_frames_cv2, path, fps)
    except Exception as e:
        log.debug("cv2_extract_failed", err=str(e)[:80])

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract_frames_pil, path, fps)
    except Exception as e:
        log.debug("pil_extract_failed", err=str(e)[:80])

    return FrameResult(
        error="No frame extractor available (install opencv-python-headless or Pillow)",
        provider="stub",
    )


# ── Public: analyze_video ─────────────────────────────────────

async def analyze_video(
    video_path:    Union[str, Path],
    max_frames:    int   = 8,
    fps:           float = 0.5,
    question:      str   = "Describe what happens in this video, step by step.",
) -> VideoAnalysisResult:
    """
    Analyze a video by extracting sampled frames and sending them to GPT-4o Vision.
    max_frames: max frames to send to the API (cost control).
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return VideoAnalysisResult(
            description="[Vision unavailable: OPENAI_API_KEY not set]",
            provider="stub",
            error="OPENAI_API_KEY not set",
        )

    # 1. Extract frames
    frame_result = await extract_video_frames(video_path, fps=fps)
    if not frame_result.ok:
        return VideoAnalysisResult(
            description=f"[Frame extraction failed: {frame_result.error}]",
            provider="stub",
            error=frame_result.error,
        )

    # 2. Sample frames evenly
    total   = len(frame_result.frames)
    step    = max(1, total // max_frames)
    sampled = frame_result.frames[::step][:max_frames]
    log.info("video_analyze_frames", total=total, sampled=len(sampled))

    # 3. Build GPT-4o content list
    content: list[dict] = [{"type": "text", "text": question}]
    for frame_bytes in sampled:
        b64 = base64.b64encode(frame_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
        })

    # 4. GPT-4o Vision call
    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
            max_tokens=1024,
        )
        description = resp.choices[0].message.content or ""
        log.info("video_analyzed", chars=len(description))
        return VideoAnalysisResult(
            description=description,
            frame_count=total,
            sampled=len(sampled),
            provider="gpt4o_vision",
        )
    except Exception as e:
        log.error("analyze_video_failed", err=str(e)[:120])
        return VideoAnalysisResult(
            description=f"[Vision error: {e}]",
            frame_count=total,
            sampled=len(sampled),
            provider="gpt4o_vision",
            error=str(e),
        )


# ── Capability probe ──────────────────────────────────────────

def video_capabilities() -> dict:
    _key = os.getenv("OPENAI_API_KEY", "")
    has_openai = bool(_key) and not _key.startswith("sk-or-")  # OpenRouter can't do Vision API
    has_cv2 = False
    try:
        import cv2  # noqa: F401
        has_cv2 = True
    except ImportError:
        _silent_log.debug("suppressed_exception", src='video.py')
    has_pil = False
    try:
        from PIL import Image  # noqa: F401
        has_pil = True
    except ImportError:
        _silent_log.debug("suppressed_exception", src='video.py')

    return {
        "video_generate": False,   # stub only for now
        "frame_extract_cv2": has_cv2,
        "frame_extract_pil": has_pil,
        "video_analyze_vision": has_openai and (has_cv2 or has_pil),
        "stub": True,
    }


# ── Missing import fix for PIL branch ────────────────────────
import io  # noqa: E402  (needed by _extract_frames_pil)
_silent_log = __import__("structlog").get_logger(__name__)
