"""Analyse COMPLÈTE de vidéos YouTube : audio + visuel.

1. Transcription intégrale (youtube-transcript-api) — tout ce qui est dit, début→fin.
2. Échantillonnage de frames sur toute la durée (yt-dlp basse résolution + ffmpeg).
3. Analyse visuelle des frames par un modèle multimodal (OpenRouter).

`analyze_youtube(url)` renvoie un dict {title, duration, transcript, visual} ; la synthèse
finale (réponse à la question de l'utilisateur) est laissée à la cognition de Béa pour
garder la qualité du cerveau principal.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import subprocess  # nosec B404
import tempfile
from pathlib import Path

import httpx

_VIDEO_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|live/|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_VISION_MODEL = os.getenv("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
_VISION_FALLBACK = os.getenv("VISION_FALLBACK",
                             "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")


def extract_video_id(url: str) -> str | None:
    m = _VIDEO_RE.search(url or "")
    return m.group(1) if m else None


def _fetch_transcript(video_id: str) -> str:
    """Transcription intégrale (FR/EN), tolérante aux versions de l'API."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        langs = ["fr", "en", "fr-FR", "en-US"]
        try:                                   # API récente (instance .fetch)
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=langs)
            return " ".join(getattr(s, "text", "") for s in fetched).strip()
        except Exception:                      # noqa: BLE001  API ancienne (classmethod)
            segs = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
            return " ".join(s.get("text", "") for s in segs).strip()
    except Exception:                          # noqa: BLE001  pas de sous-titres
        return ""


def _download_and_frames(url: str, n_frames: int, workdir: str) -> tuple[dict, list[str]]:
    """Télécharge la vidéo (basse résolution) et extrait n_frames réparties. Bloquant."""
    import yt_dlp

    out = str(Path(workdir) / "v.mp4")
    opts = {"format": "worst[ext=mp4]/worst", "outtmpl": out,
            "quiet": True, "noplaylist": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    meta = {"title": info.get("title", ""), "duration": int(info.get("duration") or 0),
            "channel": info.get("uploader", "")}
    duration = max(meta["duration"], 1)
    interval = max(duration / n_frames, 1)
    pattern = str(Path(workdir) / "f_%03d.png")
    subprocess.run(  # nosec B603 B607
        ["ffmpeg", "-i", out, "-vf", f"fps=1/{interval},scale=512:-1",
         "-frames:v", str(n_frames), "-y", pattern],
        capture_output=True, timeout=180, check=False)
    frames = sorted(str(p) for p in Path(workdir).glob("f_*.png"))
    return meta, frames[:n_frames]


async def _analyze_frames(frames: list[str], title: str) -> str:
    """Analyse visuelle des frames échantillonnées via un modèle multimodal."""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key or not frames:
        return ""
    content: list[dict] = [{"type": "text", "text":
        f"Voici {len(frames)} images échantillonnées sur toute la durée de la vidéo "
        f"« {title} ». Décris ce qu'on y VOIT (scènes, personnes, texte à l'écran, "
        f"actions, ambiance), dans l'ordre chronologique."}]
    for fp in frames:
        try:
            b64 = base64.b64encode(Path(fp).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        except Exception:  # noqa: BLE001
            continue
    async with httpx.AsyncClient(timeout=120) as c:
        for model in (_VISION_MODEL, _VISION_FALLBACK):
            try:
                r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                                 json={"model": model,
                                       "messages": [{"role": "user", "content": content}]},
                                 headers={"Authorization": f"Bearer {key}"})
                txt = (((r.json().get("choices") or [{}])[0].get("message") or {})
                       .get("content") or "").strip()
                if txt:
                    return txt
            except Exception:  # noqa: BLE001
                continue
    return ""


async def analyze_youtube(url: str, n_frames: int = 8) -> dict:
    """Analyse complète : {ok, title, duration, transcript, visual, error}."""
    vid = extract_video_id(url)
    if not vid:
        return {"ok": False, "error": "URL YouTube non reconnue"}
    transcript = await asyncio.to_thread(_fetch_transcript, vid)
    meta: dict = {}
    visual = ""
    with tempfile.TemporaryDirectory() as wd:
        try:
            meta, frames = await asyncio.to_thread(_download_and_frames, url, n_frames, wd)
            visual = await _analyze_frames(frames, meta.get("title", ""))
        except Exception as e:  # noqa: BLE001  (vidéo indispo / bloquée) -> transcript seul
            meta = meta or {}
            meta.setdefault("error_dl", str(e)[:160])
    if not transcript and not visual:
        return {"ok": False, "error": "ni transcription ni visuel exploitables",
                "title": meta.get("title", "")}
    return {"ok": True, "title": meta.get("title", ""), "channel": meta.get("channel", ""),
            "duration": meta.get("duration", 0),
            "transcript": transcript[:12000], "visual": visual[:4000]}
