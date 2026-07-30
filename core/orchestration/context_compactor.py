"""
ContextCompactor — gestion de la fenêtre de contexte pour les missions longues.
Inspiré de src/services/compact/ (Claude Code source, 2026-03-31).

Stratégie :
- Estimation rapide des tokens (heuristique : ~4 chars/token)
- Seuil configurable (défaut : 80 000 tokens → 80% d'un contexte 100k)
- Compaction : résumé LLM des messages anciens + injection dans Qdrant
- Le résumé remplace les anciens messages dans la liste retournée
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────────────

DEFAULT_TOKEN_THRESHOLD = 80_000     # tokens avant déclenchement compaction
DEFAULT_KEEP_RECENT = 10             # nombre de messages récents à toujours garder
CHARS_PER_TOKEN = 4                  # heuristique : 1 token ≈ 4 caractères
COMPACTION_SUMMARY_MAX_TOKENS = 2000 # taille max du résumé généré


# ── Types ──────────────────────────────────────────────────────────────────────

@dataclass
class Message:
    role: str        # "user" | "assistant" | "system" | "tool"
    content: str
    metadata: dict = field(default_factory=dict)

    def token_estimate(self) -> int:
        return max(1, len(self.content) // CHARS_PER_TOKEN)

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, **self.metadata}


@dataclass
class CompactionResult:
    original_count: int
    compacted_count: int
    tokens_before: int
    tokens_after: int
    summary: str
    stored_in_memory: bool = False


# ── Compactor ──────────────────────────────────────────────────────────────────

class ContextCompactor:
    """
    Surveille et compacte le contexte d'une mission.

    Usage :
        compactor = ContextCompactor(mission_id="abc123")
        messages, result = await compactor.maybe_compact(messages)
        if result:
            logger.info("Compacté: %d → %d messages", result.original_count, result.compacted_count)
    """

    def __init__(
        self,
        mission_id: str,
        token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        memory_facade=None,   # core.memory_facade.MemoryFacade (optionnel)
        llm_client=None,      # callable async(prompt: str) -> str (optionnel)
    ):
        self.mission_id = mission_id
        self.token_threshold = token_threshold
        self.keep_recent = keep_recent
        self._memory_facade = memory_facade
        self._llm_client = llm_client
        self._compaction_count = 0

    def estimate_tokens(self, messages: list[Message]) -> int:
        return sum(m.token_estimate() for m in messages)

    def needs_compaction(self, messages: list[Message]) -> bool:
        total = self.estimate_tokens(messages)
        if total > self.token_threshold:
            logger.debug(
                "Contexte mission %s : %d tokens estimés (seuil: %d)",
                self.mission_id, total, self.token_threshold,
            )
            return True
        return False

    async def maybe_compact(
        self, messages: list[Message]
    ) -> tuple[list[Message], CompactionResult | None]:
        """
        Compacte si nécessaire.

        Returns:
            (messages_compactés, CompactionResult) ou (messages_originaux, None)
        """
        if not self.needs_compaction(messages):
            return messages, None

        return await self._compact(messages)

    async def _compact(
        self, messages: list[Message]
    ) -> tuple[list[Message], CompactionResult]:
        tokens_before = self.estimate_tokens(messages)
        original_count = len(messages)

        if len(messages) <= self.keep_recent:
            logger.warning(
                "Mission %s : compaction demandée mais seulement %d messages",
                self.mission_id, len(messages),
            )
            return messages, CompactionResult(
                original_count=original_count,
                compacted_count=original_count,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                summary="(rien à compacter)",
            )

        to_summarize = messages[: -self.keep_recent]
        to_keep = messages[-self.keep_recent :]

        summary = await self._generate_summary(to_summarize)

        summary_message = Message(
            role="system",
            content=f"[RÉSUMÉ DES ÉCHANGES PRÉCÉDENTS]\n{summary}",
            metadata={"compaction": True, "summarized_count": len(to_summarize)},
        )
        compacted = [summary_message] + to_keep
        tokens_after = self.estimate_tokens(compacted)

        stored = False
        if self._memory_facade is not None:
            stored = await self._store_summary(summary, to_summarize)

        self._compaction_count += 1
        result = CompactionResult(
            original_count=original_count,
            compacted_count=len(compacted),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary=summary,
            stored_in_memory=stored,
        )
        logger.info(
            "Mission %s : compaction #%d — %d→%d msgs, %d→%d tokens",
            self.mission_id, self._compaction_count,
            original_count, len(compacted),
            tokens_before, tokens_after,
        )
        return compacted, result

    async def _generate_summary(self, messages: list[Message]) -> str:
        if self._llm_client is None:
            return self._heuristic_summary(messages)

        prompt = self._build_summary_prompt(messages)
        try:
            summary = await self._llm_client(prompt)
            return summary[: COMPACTION_SUMMARY_MAX_TOKENS * CHARS_PER_TOKEN]
        except Exception as e:
            logger.warning("LLM summary failed, using heuristic: %s", e)
            return self._heuristic_summary(messages)

    def _heuristic_summary(self, messages: list[Message]) -> str:
        lines = []
        for msg in messages:
            prefix = f"[{msg.role.upper()}]"
            snippet = msg.content[:200].replace("\n", " ")
            if len(msg.content) > 200:
                snippet += "…"
            lines.append(f"{prefix} {snippet}")
        return "\n".join(lines)

    def _build_summary_prompt(self, messages: list[Message]) -> str:
        history = "\n".join(
            f"{m.role.upper()}: {m.content[:500]}" for m in messages
        )
        return (
            f"Résume de façon concise (max {COMPACTION_SUMMARY_MAX_TOKENS} tokens) "
            f"les échanges suivants d'une mission IA. "
            f"Conserve les décisions importantes, les résultats obtenus, "
            f"et les erreurs rencontrées.\n\n"
            f"HISTORIQUE :\n{history}\n\n"
            f"RÉSUMÉ :"
        )

    async def _store_summary(
        self, summary: str, original_messages: list[Message]
    ) -> bool:
        try:
            payload = {
                "mission_id": self.mission_id,
                "type": "context_compaction",
                "summary": summary,
                "message_count": len(original_messages),
                "timestamp": time.time(),
                "compaction_index": self._compaction_count,
            }
            await self._memory_facade.store(
                collection="episodic",
                text=summary,
                metadata=payload,
            )
            logger.debug(
                "Résumé compaction #%d stocké dans Qdrant pour mission %s",
                self._compaction_count, self.mission_id,
            )
            return True
        except Exception as e:
            logger.warning("Stockage Qdrant échoué: %s", e)
            return False
