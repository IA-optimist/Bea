"""
BEA MAX — Voice & Call System (Phase 10)
Exposes CallManager and VoicePipeline.
"""
from modules.voice.call_manager import CallManager
from modules.voice.voice_pipeline import VoicePipeline

__all__ = ["CallManager", "VoicePipeline"]
