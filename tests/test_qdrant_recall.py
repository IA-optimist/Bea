from __future__ import annotations

from types import SimpleNamespace

from memory.qdrant_recall import QdrantMemoryRecall, QdrantRecallConfig, config_from_settings


def test_config_from_settings_prefers_settings(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://env-qdrant:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "env-key")
    settings = SimpleNamespace(qdrant_url="http://settings-qdrant:6333/", qdrant_api_key="settings-key")

    config = config_from_settings(settings)

    assert config.url == "http://settings-qdrant:6333"
    assert config.api_key == "settings-key"
    assert config.collection == "beamax_memory_384"


def test_to_memory_result_maps_payload_metadata():
    recall = QdrantMemoryRecall(QdrantRecallConfig(url="http://qdrant:6333", api_key=""))
    hit = {
        "id": "point-1",
        "score": 0.82,
        "payload": {
            "key": "bea:self_improvement:no_secret_memory",
            "tags": ["bea", "securite"],
            "text": "Do not store secret values.",
            "category": "bea_self_improvement",
            "source": "codex_self_improvement_seed_2026-06-21",
            "ts": 123.0,
        },
    }

    result = recall._to_memory_result(hit)

    assert result["id"] == "point-1"
    assert result["text"] == "Do not store secret values."
    assert result["score"] == 0.82
    assert result["backend"] == "qdrant_beamax"
    assert result["metadata"]["key"] == "bea:self_improvement:no_secret_memory"
    assert result["metadata"]["source"] == "codex_self_improvement_seed_2026-06-21"
