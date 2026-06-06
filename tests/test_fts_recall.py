"""Tests pour memory.fts_recall — SQLite FTS5 réel (stdlib), sans mock."""
from __future__ import annotations

from memory.fts_recall import FTSRecall


def test_add_and_count():
    r = FTSRecall(":memory:")
    assert r.add("le déploiement a échoué sur staging")
    assert r.add("mission de recherche marché terminée")
    assert r.count() == 2
    assert r.add("   ") is False  # vide ignoré
    assert r.count() == 2
    r.close()


def test_search_finds_relevant():
    r = FTSRecall(":memory:")
    r.add("le déploiement a échoué sur staging", kind="failure", session_id="s1")
    r.add("mission de recherche marché terminée", kind="success", session_id="s2")
    hits = r.search("déploiement")
    assert len(hits) == 1
    assert "déploiement" in hits[0]["content"]
    assert hits[0]["session_id"] == "s1"
    r.close()


def test_search_empty_query():
    r = FTSRecall(":memory:")
    r.add("contenu")
    assert r.search("") == []
    r.close()


def test_special_chars_dont_crash(tmp_path):
    # caractères qui casseraient une requête FTS brute -> repli LIKE, pas d'exception
    r = FTSRecall(str(tmp_path / "m.db"))
    r.add("rapport (Q4) : revenus +30%")
    hits = r.search('(Q4)')
    assert isinstance(hits, list)
    r.close()


def test_persistence(tmp_path):
    db = str(tmp_path / "mem.db")
    r1 = FTSRecall(db)
    r1.add("fait persistant", session_id="s9")
    r1.close()
    r2 = FTSRecall(db)
    assert r2.count() == 1
    assert r2.search("persistant")[0]["session_id"] == "s9"
    r2.close()
