"""
BEA MAX — Multimodal module
Exports all public functions and classes.
"""
from modules.multimodal.image import (
    ImageResult,
    generate_image,
    describe_image,
    image_capabilities,
)
from modules.multimodal.voice import (
    TranscriptResult,
    AudioResult,
    VoiceSession,
    speech_to_text,
    text_to_speech,
    voice_capabilities,
)
from modules.multimodal.video import (
    VideoStubResult,
    FrameResult,
    VideoAnalysisResult,
    generate_video_stub,
    extract_video_frames,
    analyze_video,
    video_capabilities,
)

__all__ = [
    # image
    "ImageResult",
    "generate_image",
    "describe_image",
    "image_capabilities",
    # voice
    "TranscriptResult",
    "AudioResult",
    "VoiceSession",
    "speech_to_text",
    "text_to_speech",
    "voice_capabilities",
    # video
    "VideoStubResult",
    "FrameResult",
    "VideoAnalysisResult",
    "generate_video_stub",
    "extract_video_frames",
    "analyze_video",
    "video_capabilities",
]
