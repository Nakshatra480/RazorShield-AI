"""
razorshield_backend/agents/policy_agent.py
───────────────────────────────────────────
LLM-powered compliance evaluator for merchant policy documents.

Evaluates:
  1. Entity registration name clearly stated
  2. Refund / return timeline with explicit day count
  3. Contact email or phone number present
  4. Privacy policy with data handling explanation
  5. Terms of Service with prohibited use clauses

Returns a structured PolicyResult with a 0.0–1.0 compliance score,
a boolean verdict, and a list of specific missing disclosures.

Retry strategy:
  - Up to 3 attempts with exponential back-off (1s → 2s → 4s).
  - On all attempts exhausted, returns a conservative low-score result
    rather than crashing the inspection pipeline.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import litellm

from razorshield_backend.config import Settings, get_settings
from razorshield_backend.scrapers.browser import PolicyTexts

logger = logging.getLogger(__name__)
litellm.drop_params = True  # silently drop params unsupported by specific models


# ─── System prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a compliance analyst evaluating merchant policy documents on behalf of a payment gateway's underwriting team.

Your task: analyse the provided policy document excerpts and return a single JSON object assessing regulatory and consumer-protection compliance.

Return ONLY valid JSON matching this exact schema — no markdown, no explanation:
{
  "is_compliant": <boolean>,
  "policy_score": <float 0.0–1.0>,
  "missing_disclosures": [<string>, ...]
}

Scoring rubric (each item worth 0.2 points):
1. Legal entity name clearly stated (business registration name, not just brand name)
2. Explicit refund/return timeline with a specific number of days
3. Contact method present: email address OR phone number
4. Privacy policy explains what data is collected, stored, and shared
5. Terms of Service references prohibited uses or acceptable use policy

Rules:
- policy_score = (number of items present) × 0.2
- is_compliant = policy_score >= 0.6 (at least 3 of 5 items present)
- missing_disclosures = list of items that are absent or vague
- If no policy text is provided, return {"is_compliant": false, "policy_score": 0.0, "missing_disclosures": ["No policy pages accessible"]}
- Be strict: partial or vague policies do NOT count as present."""


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    """Output from the Policy Compliance Agent."""
    is_compliant: bool
    policy_score: float                     # 0.0 (non-compliant) – 1.0 (fully compliant)
    missing_disclosures: list[str] = field(default_factory=list)
    agent_error: Optional[str] = None       # set only if LLM calls all failed


# ─── Agent ────────────────────────────────────────────────────────────────────

class PolicyAgent:
    """
    Stateless policy compliance evaluator.
    Instantiate once and reuse across requests.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    def _build_user_message(self, policy_texts: PolicyTexts) -> str:
        """Format policy page contents into a compact LLM prompt."""
        sections: list[str] = []
        if policy_texts.terms:
            sections.append(f"[TERMS OF SERVICE]\n{policy_texts.terms[:2500]}")
        if policy_texts.privacy:
            sections.append(f"[PRIVACY POLICY]\n{policy_texts.privacy[:2500]}")
        if policy_texts.refund:
            sections.append(f"[REFUND / RETURN POLICY]\n{policy_texts.refund[:2000]}")
        if policy_texts.contact:
            sections.append(f"[CONTACT PAGE]\n{policy_texts.contact[:1000]}")

        if not sections:
            return "No policy pages were accessible for this merchant."

        return "Evaluate the following policy documents:\n\n" + "\n\n---\n\n".join(sections)

    async def evaluate(self, policy_texts: PolicyTexts) -> PolicyResult:
        """
        Evaluate policy compliance using LiteLLM → OpenRouter.

        Retries up to 3 times with exponential back-off.
        Returns a conservative result (score=0.0) if all attempts fail.
        """
        user_message = self._build_user_message(policy_texts)

        # Short-circuit: if no text, skip LLM call entirely
        all_empty = not any([
            policy_texts.terms,
            policy_texts.privacy,
            policy_texts.refund,
            policy_texts.contact,
        ])
        if all_empty:
            return PolicyResult(
                is_compliant=False,
                policy_score=0.0,
                missing_disclosures=["No policy pages accessible"],
            )

        last_error: Optional[str] = None
        for attempt in range(3):
            try:
                response = await litellm.acompletion(
                    model=self._settings.llm_model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.0,
                    max_tokens=512,
                    api_base=self._settings.openrouter_base_url,
                    api_key=self._settings.openrouter_api_key,
                    response_format={"type": "json_object"},
                )

                raw: str = response.choices[0].message.content.strip()

                # Strip markdown code fences if model wraps response
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()

                data: dict = json.loads(raw)

                return PolicyResult(
                    is_compliant=bool(data.get("is_compliant", False)),
                    policy_score=float(
                        max(0.0, min(1.0, data.get("policy_score", 0.0)))
                    ),
                    missing_disclosures=list(data.get("missing_disclosures", [])),
                )

            except json.JSONDecodeError as exc:
                last_error = f"JSON parse error on attempt {attempt + 1}: {exc}"
                logger.warning("PolicyAgent JSON error (attempt %d): %s", attempt + 1, exc)

            except Exception as exc:
                last_error = f"LLM error on attempt {attempt + 1}: {exc}"
                logger.warning("PolicyAgent LLM error (attempt %d): %s", attempt + 1, exc)

            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s before retry 3

        logger.error("PolicyAgent exhausted all 3 attempts. Returning conservative result.")
        return PolicyResult(
            is_compliant=False,
            policy_score=0.0,
            missing_disclosures=["Policy analysis failed — treating as non-compliant"],
            agent_error=last_error,
        )
