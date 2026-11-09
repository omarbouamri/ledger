"""Gemini integration.

Three jobs, all through the official Google Gen AI Python SDK (``google-genai``):

``draft_email``   write a cold introduction email for one employer
``brief``         a short research/approach brief on one employer
``ask``           free-form question answered against the directory's own stats

Every call is wrapped so a missing key, a network failure or a blocked response
comes back as a readable string instead of a traceback in a Dash callback, and
every call is metered into ``ai_runs`` for the admin panel.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from config import settings
from jobscout import repo

log = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types
except ModuleNotFoundError:  # pragma: no cover
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

_client: Any = None


SYSTEM_PROMPT = """You are the research assistant inside JobScout, a field book \
for a freelance developer scouting employers and clients in Marrakech, Morocco.

The directory is compiled from public Google Maps listings. Each employer record \
carries: name, sector, address, phone, whether a website is on file, a public \
rating out of 5, a review count, and a JobScout opportunity score from 0-9 that \
blends rating, review volume, the absence of a website, and reachability by phone.

House style:
- Plain, direct, specific. No marketing voice, no exclamation marks, no emoji.
- Never invent facts about an employer. If a field is missing, say it is missing.
- Keep messages short enough to read on a phone: under 150 words.
- Moroccan business context: French and Arabic are common; English is fine for \
tech firms. Mention language choice only if asked.
- When you are unsure, say so in one line rather than hedging throughout."""

# Rough thinking budgets per effort setting. -1 lets the model decide.
_EFFORT_BUDGET = {"low": 0, "medium": -1, "high": 24576}


@dataclass(slots=True)
class AIResult:
    ok: bool
    text: str
    subject: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def error(self) -> str:
        return "" if self.ok else self.text


def available() -> bool:
    return bool(genai is not None and settings.ai_enabled())


def status_note() -> str:
    if genai is None:
        return "The `google-genai` package is not installed - run `pip install google-genai`."
    if not settings.ai_enabled():
        return "No GEMINI_API_KEY found. Set it in your environment or .env to enable AI drafting."
    return f"Connected · {settings.AI_MODEL}"


def _get_client():
    global _client
    if _client is None:
        if genai is None:
            raise RuntimeError("google-genai package is not installed")
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=genai_types.HttpOptions(timeout=120_000),
        )
    return _client


def _thinking_config() -> Any:
    """Thinking budget for the configured effort, clamped to what the model allows."""
    budget = _EFFORT_BUDGET.get(settings.AI_EFFORT.strip().lower(), -1)
    # The Pro models cannot switch thinking off; their floor is 128 tokens.
    if budget == 0 and "pro" in settings.AI_MODEL.lower():
        budget = 128
    return genai_types.ThinkingConfig(thinking_budget=budget)


def _employer_facts(emp: Mapping[str, Any]) -> str:
    rating = emp.get("rating")
    reviews = emp.get("reviews")
    return json.dumps(
        {
            "name": emp.get("name"),
            "sector": emp.get("sector"),
            "address": emp.get("address") or None,
            "phone": emp.get("phone") or None,
            "website": emp.get("website") or None,
            "has_website": bool(emp.get("has_website")),
            "public_rating": rating if rating is not None else "not rated",
            "review_count": int(reviews) if reviews else 0,
            "opportunity_score": emp.get("score"),
        },
        ensure_ascii=False,
        indent=1,
    )


def _blocked_reason(response: Any) -> str:
    """A readable reason when Gemini returns no usable text, else ""."""
    feedback = getattr(response, "prompt_feedback", None)
    block = getattr(feedback, "block_reason", None)
    if block:
        return f"Gemini blocked this prompt ({getattr(block, 'name', block)})."

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "Gemini returned no candidates."
    finish = getattr(candidates[0], "finish_reason", None)
    name = str(getattr(finish, "name", finish) or "").upper()
    if name in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}:
        return f"Gemini declined this request ({name.lower().replace('_', ' ')})."
    if name == "MAX_TOKENS":
        return "Gemini hit the output limit before finishing - raise JOBSCOUT_AI_MAX_TOKENS."
    return ""


def _call(
    user_id: int | None,
    kind: str,
    prompt: str,
    *,
    max_tokens: int | None = None,
) -> AIResult:
    """One non-streaming generate_content request, fully guarded and metered."""
    if not available():
        return AIResult(False, status_note())

    model = settings.AI_MODEL
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=max_tokens or settings.AI_MAX_TOKENS,
                thinking_config=_thinking_config(),
            ),
        )
    except Exception as exc:  # network, auth, rate limit, bad request
        log.warning("AI call failed (%s): %s", kind, exc)
        repo.log_ai_run(user_id, kind, model, 0, 0, ok=False)
        return AIResult(False, f"Gemini could not be reached: {exc}")

    usage = getattr(response, "usage_metadata", None)
    in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
    out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
    out_tok += int(getattr(usage, "thoughts_token_count", 0) or 0)

    refusal = _blocked_reason(response)
    if refusal:
        repo.log_ai_run(user_id, kind, model, in_tok, out_tok, ok=False)
        return AIResult(False, refusal)

    try:
        text = (response.text or "").strip()
    except Exception:  # the SDK raises when a candidate carries no text part
        text = ""

    repo.log_ai_run(user_id, kind, model, in_tok, out_tok, ok=bool(text))
    if not text:
        return AIResult(False, "Gemini returned an empty response - try again.")
    return AIResult(True, text, model=model, input_tokens=in_tok, output_tokens=out_tok)


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def draft_email(
    user_id: int,
    emp: Mapping[str, Any],
    *,
    sender_name: str,
    goal: str = "introduce myself and ask for a short call",
    tone: str = "direct and warm",
    language: str = "English",
    extra: str = "",
) -> AIResult:
    """Draft a cold introduction email. Returns subject on ``.subject``."""
    prompt = f"""Write one cold introduction email.

Employer record:
{_employer_facts(emp)}

Sender's name: {sender_name or "the sender"}
Goal of the email: {goal}
Tone: {tone}
Language: {language}
{("Extra context from the sender: " + extra) if extra.strip() else ""}

Rules:
- Open with a specific, verifiable observation from the record above.
- One clear ask. No multiple questions.
- Under 150 words in the body.
- Sign off with the sender's name on its own line.
- Do not invent a contact person's name; address the business if none is known.

Return exactly this shape and nothing else:
SUBJECT: <one line, under 60 characters>
BODY:
<the email body>"""
    result = _call(user_id, "draft_email", prompt, max_tokens=1600)
    if not result.ok:
        return result

    subject, body = "", result.text
    lines = result.text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("SUBJECT:"):
            subject = stripped[8:].strip()
        elif stripped.upper().startswith("BODY:"):
            body = "\n".join(lines[i + 1 :]).strip()
            break
    result.subject = subject
    result.text = body
    return result


def brief(user_id: int, emp: Mapping[str, Any]) -> AIResult:
    """A short approach brief: what this employer is, and how to open."""
    prompt = f"""Write a short approach brief for this employer.

{_employer_facts(emp)}

Use exactly these four headings, each with 1-3 short bullets:
Read on the business
Likely gap
Opening angle
Risks

Be concrete about what the record shows and explicit about what it does not.
Under 200 words total."""
    return _call(user_id, "brief", prompt, max_tokens=1600)


def ask(user_id: int, question: str) -> AIResult:
    """Answer a question about the directory, grounded in real aggregates."""
    stats = repo.overview_metrics(user_id)
    sectors = repo.sector_breakdown()
    top = sectors.head(12).to_dict(orient="records") if not sectors.empty else []
    context = json.dumps({"totals": stats, "sectors": top}, ensure_ascii=False, indent=1)

    prompt = f"""Here are the current aggregate statistics for the JobScout directory:

{context}

Question from the user: {question.strip()}

Answer using only these numbers plus general business judgement. If the data \
cannot answer the question, say which figure is missing. Be brief - a few short \
paragraphs or a tight list."""
    return _call(user_id, "ask", prompt, max_tokens=2000)
