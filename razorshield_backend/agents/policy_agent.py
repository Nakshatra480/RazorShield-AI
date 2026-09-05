"""
razorshield_backend/agents/policy_agent.py
───────────────────────────────────────────
Compliance evaluator for merchant policy documents.

Evaluates five disclosures, each worth 0.2 of the compliance score:
  1. Legal entity registration name clearly stated
  2. Refund / return timeline with an explicit day count
  3. Contact email or phone number present
  4. Privacy policy explaining data handling
  5. Terms of Service referencing prohibited / acceptable use

Primary path is an LLM judgement (via the shared LLMClient). When the provider
is unavailable the agent falls back to a deterministic rule-based scorer over
the same rubric instead of returning 0.0.

Why the fallback matters
────────────────────────
The previous version returned ``policy_score=0.0`` whenever the LLM failed,
labelled "conservative". It is not conservative — it is wrong in both
directions: a fully compliant merchant with a 30-day refund policy and a
registered company number scored 0.0 and was pushed toward HIGH_RISK. With a
dead API key (the state this deployment was in) *every* merchant scored 0.0,
making the policy signal pure noise while still carrying 40% of the risk weight.
The rule-based scorer keeps the signal meaningful when the LLM is down, and the
result is tagged ``evaluated_by`` so downstream consumers know which ran.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from razorshield_backend.agents.llm import LLMClient, LLMUnavailable
from razorshield_backend.config import Settings, get_settings
from razorshield_backend.scrapers.browser import PolicyTexts

logger = logging.getLogger(__name__)


# ─── System prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a compliance analyst evaluating merchant policy documents on behalf of a payment gateway's underwriting team.

Your task: analyse the provided policy document excerpts and return a single JSON object assessing regulatory and consumer-protection compliance.

Return ONLY valid JSON matching this exact schema — no markdown, no explanation:
{
  "is_compliant": <boolean>,
  "policy_score": <float 0.0-1.0>,
  "missing_disclosures": [<string>, ...]
}

Scoring rubric (each item worth 0.2 points):
1. Legal entity name clearly stated (business registration name, not just brand name)
2. Explicit refund/return timeline with a specific number of days
3. Contact method present: email address OR phone number
4. Privacy policy explains what data is collected, stored, and shared
5. Terms of Service references prohibited uses or acceptable use policy

Rules:
- policy_score = (number of items present) x 0.2
- is_compliant = policy_score >= 0.6 (at least 3 of 5 items present)
- missing_disclosures = list of items that are absent or vague
- If no policy text is provided, return {"is_compliant": false, "policy_score": 0.0, "missing_disclosures": ["No policy pages accessible"]}
- Be strict: partial or vague policies do NOT count as present."""


EvaluatedBy = Literal["llm", "heuristic", "none", "blocked"]


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    """Output from the Policy Compliance Agent."""
    is_compliant: bool
    policy_score: float                     # 0.0 (non-compliant) – 1.0 (fully compliant)
    missing_disclosures: list[str] = field(default_factory=list)
    agent_error: Optional[str] = None       # set when the LLM path was unavailable
    evaluated_by: EvaluatedBy = "llm"       # which scorer actually produced this
    # True when compliance could not be assessed at all (the site served a bot
    # challenge). The orchestrator must then exclude policy from the weighted
    # score instead of treating 0.0 as a measured result — absence of evidence
    # is not evidence of non-compliance.
    inconclusive: bool = False


# ─── Deterministic rubric checks (LLM-free fallback) ──────────────────────────

_ENTITY_PATTERNS = (
    r"\b(?:ltd|limited|llc|l\.l\.c\.|inc\.?|incorporated|gmbh|b\.?v\.?|s\.?a\.?r\.?l"
    r"|pvt\.?\s*ltd|private limited|plc|co\.,? ?ltd|corporation|corp\.)\b",
    r"\b(?:company|business|registration|registered|incorporation)\s*(?:number|no\.?|#|id)\b",
    r"\b(?:cin|gstin|vat|ein|abn|company\s*reg)\b",
)

_REFUND_DAYS_PATTERNS = (
    r"\b(?:within|up to|after)\s+\d{1,3}\s*(?:calendar\s+|business\s+|working\s+)?days?\b",
    r"\b\d{1,3}\s*(?:calendar\s+|business\s+|working\s+)?days?\s+(?:refund|return|money[- ]back|guarantee|window|period)\b",
    r"\b(?:refund|return)\s+(?:period|window)\s+of\s+\d{1,3}\b",
)

_EMAIL_RE = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
# Deliberately conservative: 7+ digits with separators, so prices and dates
# ("$1,299", "2024-01-15") do not read as phone numbers.
_PHONE_RE = r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{3,4}[\s.\-]\d{3,4}(?:[\s.\-]\d{2,4})?"

_PRIVACY_COLLECT = (
    r"\b(?:we|us|our)\b.{0,40}\b(?:collect|gather|obtain|process|store|retain)\b",
    r"\b(?:personal|customer|user)\s+(?:data|information)\b",
    r"\b(?:cookies?|ip address|email address|payment information)\b",
)
_PRIVACY_SHARING = (
    r"\b(?:third[- ]part(?:y|ies)|partners?|service providers?|processors?)\b",
    r"\b(?:do not|never|don't)\s+(?:sell|share|rent)\b",
    r"\b(?:encrypt|secure(?:ly)?|stored|deletion|opt[- ]out|gdpr|ccpa)\b",
)

_PROHIBITED_USE_PATTERNS = (
    r"\bprohibited\s+(?:uses?|activit(?:y|ies)|conduct)\b",
    r"\bacceptable\s+use\b",
    r"\b(?:you\s+)?(?:may\s+not|must\s+not|shall\s+not|are\s+prohibited\s+from)\b",
    r"\b(?:unlawful|illegal|fraudulent)\s+(?:use|activit|purpose)",
    r"\brestricted\s+(?:uses?|activities)\b",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _has_contact(text: str) -> bool:
    if re.search(_EMAIL_RE, text):
        return True
    # Require an explicit phone cue alongside the digits to avoid matching
    # order numbers or prices.
    if re.search(r"\b(?:tel|phone|call|mobile|contact)\b", text, re.IGNORECASE):
        return bool(re.search(_PHONE_RE, text))
    return False


def evaluate_policy_heuristic(policy_texts: PolicyTexts) -> PolicyResult:
    """
    Rule-based implementation of the same five-item rubric the LLM uses.

    Deterministic and dependency-free — this is what runs when the LLM provider
    is unreachable, and it is also used directly by the unit tests.
    """
    terms = policy_texts.terms or ""
    privacy = policy_texts.privacy or ""
    refund = policy_texts.refund or ""
    contact = policy_texts.contact or ""
    combined = "\n".join([terms, privacy, refund, contact])

    if not combined.strip():
        return PolicyResult(
            is_compliant=False,
            policy_score=0.0,
            missing_disclosures=["No policy pages accessible"],
            evaluated_by="heuristic",
        )

    missing: list[str] = []
    present = 0

    # 1. Legal entity identification
    if _matches_any(combined, _ENTITY_PATTERNS):
        present += 1
    else:
        missing.append("Legal entity registration name not clearly stated")

    # 2. Refund timeline with an explicit day count
    if _matches_any(f"{refund}\n{terms}", _REFUND_DAYS_PATTERNS):
        present += 1
    else:
        missing.append("No explicit refund/return timeline with a day count")

    # 3. Reachable contact method
    if _has_contact(combined):
        present += 1
    else:
        missing.append("No contact email or phone number found")

    # 4. Privacy policy describing collection AND handling/sharing
    if privacy.strip() and _matches_any(privacy, _PRIVACY_COLLECT) and _matches_any(
        privacy, _PRIVACY_SHARING
    ):
        present += 1
    else:
        missing.append("Privacy policy does not explain data collection and sharing")

    # 5. Prohibited / acceptable use clause
    if _matches_any(f"{terms}\n{privacy}", _PROHIBITED_USE_PATTERNS):
        present += 1
    else:
        missing.append("Terms of Service lacks a prohibited/acceptable use clause")

    score = round(present * 0.2, 4)
    return PolicyResult(
        is_compliant=score >= 0.6,
        policy_score=score,
        missing_disclosures=missing,
        evaluated_by="heuristic",
    )


# ─── Agent ────────────────────────────────────────────────────────────────────

class PolicyAgent:
    """
    Stateless policy compliance evaluator.
    Instantiate once and reuse across requests.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Sharing one client across agents shares the circuit-breaker state,
        # so a dead provider is discovered once per minute, not once per call.
        self._llm = llm_client or LLMClient(self._settings)

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

    @staticmethod
    def _parse_response(raw: str) -> PolicyResult:
        """Parse the model's JSON payload, tolerating markdown code fences."""
        text = raw.strip()
        if text.startswith("```"):
            # ```json\n{...}\n``` → {...}
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()

        # Some models prepend prose before the object; take the outermost braces.
        if not text.startswith("{"):
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                text = text[start : end + 1]

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

        raw_score = data.get("policy_score", 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            raise ValueError(f"policy_score is not numeric: {raw_score!r}")
        score = max(0.0, min(1.0, score))

        disclosures = data.get("missing_disclosures", [])
        if not isinstance(disclosures, list):
            disclosures = [str(disclosures)]

        return PolicyResult(
            is_compliant=bool(data.get("is_compliant", False)),
            policy_score=score,
            missing_disclosures=[str(d) for d in disclosures],
            evaluated_by="llm",
        )

    async def evaluate(
        self,
        policy_texts: PolicyTexts,
        *,
        blocked: bool = False,
        block_reason: Optional[str] = None,
    ) -> PolicyResult:
        """
        Evaluate policy compliance.

        Tries the LLM first; on provider failure falls back to the deterministic
        rubric scorer. Never raises — the inspection pipeline must always get a
        usable result.

        `blocked` says the site served an anti-bot challenge rather than its real
        content. In that case compliance is *unknown*, not zero.
        """
        all_empty = not any(
            [policy_texts.terms, policy_texts.privacy, policy_texts.refund, policy_texts.contact]
        )

        if all_empty and blocked:
            # We never saw the merchant's site. Scoring 0.0 here would penalise
            # every large merchant behind a WAF as if they published no policies.
            return PolicyResult(
                is_compliant=False,
                policy_score=0.0,
                missing_disclosures=[
                    f"Compliance could not be verified — site blocked automated inspection"
                    f"{f' ({block_reason})' if block_reason else ''}"
                ],
                evaluated_by="blocked",
                inconclusive=True,
                agent_error=block_reason,
            )

        if all_empty:
            # No text to judge — skip the LLM call entirely. This is a genuine
            # zero: the site was reachable and disclosed nothing.
            return PolicyResult(
                is_compliant=False,
                policy_score=0.0,
                missing_disclosures=["No policy pages accessible"],
                evaluated_by="none",
            )

        user_message = self._build_user_message(policy_texts)

        try:
            raw = await self._llm.complete(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.0,
                max_tokens=512,
                json_mode=True,
            )
            return self._parse_response(raw)

        except LLMUnavailable as exc:
            logger.warning(
                "PolicyAgent falling back to heuristic scorer — LLM unavailable: %s",
                exc.reason,
            )
            result = evaluate_policy_heuristic(policy_texts)
            result.agent_error = f"LLM unavailable: {exc.reason}"
            return result

        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "PolicyAgent could not parse the model response (%s) — using heuristic scorer.",
                exc,
            )
            result = evaluate_policy_heuristic(policy_texts)
            result.agent_error = f"Malformed LLM response: {exc}"
            return result
