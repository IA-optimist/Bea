"""
Self-Confidence Scoring for BeaMax
Metacognitive awareness - agent evaluates its own output quality.
"""
from __future__ import annotations
from typing import Optional, Dict, Any
import structlog

log = structlog.get_logger(__name__)


class ConfidenceScorer:
    """
    Evaluates agent's confidence in its own outputs.
    
    Enables self-correction and uncertainty quantification.
    Inspired by Constitutional AI and self-critique methods.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def score_output(
        self,
        task: str,
        output: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Score confidence in output quality.
        
        Returns:
            - confidence: 0.0-1.0 score
            - reasoning: explanation
            - issues: list of detected problems
            - should_retry: bool recommendation
        """

        prompt = self._build_scoring_prompt(task, output, context)

        try:
            # Compat: use LangChain invoke (sync) if available; fallback to heuristic
            content = None
            if hasattr(self.llm, 'invoke'):
                from langchain_core.messages import HumanMessage
                resp = self.llm.invoke([HumanMessage(content=prompt)])
                content = resp.content if hasattr(resp, 'content') else str(resp)
            elif hasattr(self.llm, 'chat'):
                response = self.llm.chat.completions.create(
                    model="google/gemini-2.0-flash-001",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.3,
                )
                content = response.choices[0].message.content
            result = self._parse_score_response(content) if content else {
                "confidence": 0.6, "reasoning": "heuristic",
                "issues": [], "should_retry": False
            }

            log.info(
                "confidence_scored",
                task=task[:50],
                confidence=result["confidence"],
                should_retry=result["should_retry"]
            )

            return result

        except Exception as e:
            log.error("confidence_scoring_failed", err=str(e))
            return {
                "confidence": 0.5,  # Neutral when scoring fails
                "reasoning": "Scoring failed",
                "issues": ["Unable to evaluate"],
                "should_retry": False
            }

    async def _llm_call(self, prompt: str, max_tokens: int = 300, temperature: float = 0.3) -> str:
        """Compat helper: works with both LangChain ChatOpenAI and raw OpenAI client."""
        try:
            if hasattr(self.llm, 'ainvoke'):
                from langchain_core.messages import HumanMessage
                resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
                return resp.content if hasattr(resp, 'content') else str(resp)
            else:
                resp = self.llm.chat.completions.create(
                    model="google/gemini-2.0-flash-001",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                return resp.choices[0].message.content
        except Exception as e:
            log.error("self_confidence_llm_failed", err=str(e))
            return None

    def _build_scoring_prompt(self, task: str, output: str, context: Optional[str]) -> str:
        """Build prompt for self-evaluation."""

        ctx_section = f"\n\nContext:\n{context}" if context else ""

        return f"""You are evaluating the quality and correctness of an AI agent's output.

Task: {task}

Agent's Output:
{output}{ctx_section}

Evaluate this output on:
1. Correctness - Is it factually accurate?
2. Completeness - Does it fully address the task?
3. Clarity - Is it clear and well-structured?
4. Safety - Are there any risks or issues?

Respond in this EXACT format:
CONFIDENCE: [0.0-1.0 score]
REASONING: [Brief explanation]
ISSUES: [Comma-separated list of problems, or "None"]
SHOULD_RETRY: [YES or NO]

Example:
CONFIDENCE: 0.85
REASONING: Output is accurate and complete, minor formatting issues
ISSUES: Verbose formatting, missing example
SHOULD_RETRY: NO"""

    def _parse_score_response(self, response: str) -> Dict[str, Any]:
        """Parse structured scoring response."""

        lines = [l.strip() for l in response.split("\n") if l.strip()]
        result = {
            "confidence": 0.5,
            "reasoning": "",
            "issues": [],
            "should_retry": False
        }

        for line in lines:
            if line.startswith("CONFIDENCE:"):
                try:
                    score = float(line.split(":", 1)[1].strip())
                    result["confidence"] = max(0.0, min(1.0, score))
                except Exception as _exc:
                    log.warning("swallowed_exception", action="self_confidence_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            elif line.startswith("REASONING:"):
                result["reasoning"] = line.split(":", 1)[1].strip()

            elif line.startswith("ISSUES:"):
                issues_str = line.split(":", 1)[1].strip()
                if issues_str.lower() != "none":
                    result["issues"] = [i.strip() for i in issues_str.split(",")]

            elif line.startswith("SHOULD_RETRY:"):
                retry = line.split(":", 1)[1].strip().upper()
                result["should_retry"] = (retry == "YES")

        return result

    def detect_errors(self, output: str) -> list[str]:
        """
        Quick error detection without full LLM call.
        
        Checks for common failure patterns.
        """
        errors = []

        # Check for error keywords
        error_keywords = ["error", "exception", "failed", "invalid", "undefined"]
        output_lower = output.lower()

        for keyword in error_keywords:
            if keyword in output_lower:
                errors.append(f"Contains error keyword: {keyword}")

        # Check for empty output
        if len(output.strip()) < 10:
            errors.append("Output too short (< 10 chars)")

        # Check for stack traces
        if "traceback" in output_lower or "at line" in output_lower:
            errors.append("Contains stack trace")

        # Check for incomplete JSON
        if output.strip().startswith("{") and not output.strip().endswith("}"):
            errors.append("Incomplete JSON output")

        return errors


class SelfCorrector:
    """
    Attempts to fix low-confidence outputs.
    
    Uses self-critique to improve quality.
    """

    def __init__(self, llm_client):
        self.llm = llm_client
        self.scorer = ConfidenceScorer(llm_client)

    async def correct_output(
        self,
        task: str,
        output: str,
        score_result: Dict[str, Any],
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        Attempt to correct low-confidence output.
        
        Returns corrected output with new confidence score.
        """

        if not score_result["should_retry"]:
            return {"output": output, "corrected": False, "score": score_result}

        log.info("self_correction_attempt", task=task[:50], issues=score_result["issues"])

        # Build correction prompt
        issues_list = "\n".join([f"- {issue}" for issue in score_result["issues"]])

        prompt = f"""The following output has quality issues. Please improve it.

Original Task: {task}

Previous Output:
{output}

Identified Issues:
{issues_list}

Generate an improved version that addresses these issues while maintaining accuracy."""

        try:
            response = self.llm.chat.completions.create(
                model="anthropic/claude-3.7-sonnet",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.5
            )

            corrected = response.choices[0].message.content

            # Re-score corrected output
            new_score = self.scorer.score_output(task, corrected)

            log.info(
                "self_correction_complete",
                original_confidence=score_result["confidence"],
                new_confidence=new_score["confidence"],
                improved=new_score["confidence"] > score_result["confidence"]
            )

            return {
                "output": corrected,
                "corrected": True,
                "original_score": score_result,
                "new_score": new_score
            }

        except Exception as e:
            log.error("self_correction_failed", err=str(e))
            return {"output": output, "corrected": False, "score": score_result}
