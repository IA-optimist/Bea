"""Wrapper LangChain minimal autour de CodexChat (gpt-5.5 direct).

Utilisé par llm_factory pour le rôle "builder" sur les missions d'exécution :
forge-builder obtient le cerveau Codex au lieu de gemma4:12b local.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterator, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

log = logging.getLogger(__name__)


class CodexDirectChatModel(BaseChatModel):
    """LangChain BaseChatModel wrappant gateway.codex_provider.CodexChat."""

    model: str = "gpt-5.5"
    temperature: float = 0.3
    timeout: int = 180

    @property
    def _llm_type(self) -> str:
        return "codex-direct-gpt55"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, self._acall(messages))
                    return future.result(timeout=self.timeout)
            else:
                return loop.run_until_complete(self._acall(messages))
        except Exception as e:
            log.error("codex_direct_generate_error", error=str(e))
            raise

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return await self._acall(messages)

    async def _acall(self, messages: List[BaseMessage]) -> ChatResult:
        from gateway.codex_provider import CodexChat  # lazy import — credentials chargées à la demande
        chat = CodexChat(model=self.model, temperature=self.temperature, timeout=self.timeout)
        resp = await chat.ainvoke(messages)
        content = resp.content if hasattr(resp, "content") else str(resp)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
