"""Optional LLM layer. Used only to *phrase* a recommendation from retrieved graph memories.
If no key is configured or the call fails, callers get the rule-based fallback and an
honest label saying so."""
import os

from study_logic import format_recommendation_markdown

DEFAULT_MODEL = "claude-sonnet-5-5"


def llm_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def model_name() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def personalize(rec: dict, weak: list[dict], recent: list[dict]) -> tuple[str, str]:
    """Return (markdown_text, source_label). source_label states what really produced the text."""
    fallback = format_recommendation_markdown(rec)
    if not llm_configured():
        return fallback, "Rule-based fallback (no LLM API key configured)"
    try:
        import anthropic

        memories = "\n".join(
            [f"- STRUGGLES_WITH {w['topic']} ({w['subject']}), difficulty {w['difficulty']}/5, reports {w['reports']}"
             for w in weak]
            + [f"- Session {r['date'][:10]}: {r['outcome']} {r['topic']} ({r['subject']})" for r in recent[:8]]
        )
        prompt = (
            "You are StudyMate AI. Write a short, encouraging revision recommendation for a student.\n"
            "Use ONLY the memories below; never invent study history.\n\n"
            f"Memories retrieved from the student's graph:\n{memories}\n\n"
            f"Chosen topic: {rec['topic']} ({rec['subject']})\nReason: {rec['reason']}\n\n"
            "Give: 1) one-sentence explanation citing the memories, 2) a 4-step study plan with "
            "times, 3) five practice questions. Use markdown."
        )
        client = anthropic.Anthropic(timeout=30.0)
        msg = client.messages.create(model=model_name(), max_tokens=900,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        if not text:
            raise RuntimeError("empty LLM response")
        return text, f"LLM ({model_name()}) using memories retrieved from FalkorDB"
    except Exception as exc:  # network, auth, model name, etc.
        return fallback, f"Rule-based fallback (LLM call failed: {type(exc).__name__})"
