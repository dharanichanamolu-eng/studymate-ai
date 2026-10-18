"""Deterministic study logic: parsing, intent detection, rule-based recommendations.
No database or network access here, so it is fully unit-testable."""
import re

KNOWN_SUBJECTS = [
    "python", "java", "javascript", "c++", "sql", "html", "css", "machine learning",
    "deep learning", "statistics", "calculus", "algebra", "linear algebra", "physics",
    "chemistry", "biology", "history", "economics", "data structures", "algorithms",
]

_DIFFICULT_WORDS = r"(?:difficult|hard|confusing|tricky|challenging)"
_INTENSIFIERS = ("very", "really", "extremely", "super", "so ")

_DIFFICULT_PATTERNS = [
    rf"^(?:i )?(?:find|found) (?P<t>.+?) (?:very |really |quite |so )?{_DIFFICULT_WORDS}",
    rf"^(?P<t>.+?) (?:is|are|was|were|seems?|seemed) (?:very |really |quite |so |extremely )?{_DIFFICULT_WORDS}",
    r"(?:struggle|struggled|struggling|have trouble|having trouble|am confused|confused|stuck) (?:with|about|by|on) (?P<t>.+)",
    r"(?:don't|do not|didn't|did not|can't|cannot) (?:really )?understand (?P<t>.+)",
]
_UNDERSTOOD_PATTERNS = [
    r"(?:understand|understood|get|got|know|grasp|grasped|am comfortable with|comfortable with|am good at) (?P<t>.+)",
]
_STUDIED_PATTERN = r"(?:studied|revised|learned|learnt|practiced|practised|reviewed|worked on|covered) (?:about )?(?P<t>.+)"

_STRIP_TRAILING = r"\s*(?:for me|today|yesterday|now|well|so far|this morning|this evening|tonight)\s*$"
_STRIP_LEADING = r"^(?:the|that|how|what|about|a|an|some|my|of)\s+"


def _clean(text: str) -> str:
    t = text.strip(" .!?,;:").lower()
    for _ in range(3):
        t = re.sub(_STRIP_TRAILING, "", t).strip()
        t = re.sub(_STRIP_LEADING, "", t).strip()
    return t


def detect_subject(text: str) -> str | None:
    low = text.lower()
    best = None
    for s in KNOWN_SUBJECTS:
        if re.search(rf"(?<![a-z+]){re.escape(s)}(?![a-z])", low):
            if best is None or len(s) > len(best):
                best = s
    return best.title() if best else None


def _strip_subject(phrase: str, subject: str | None) -> str:
    if not subject:
        return phrase
    return _clean(re.sub(re.escape(subject.lower()), "", phrase, count=1))


def parse_study_input(text: str) -> dict | None:
    """Rule-based extraction. Returns None if nothing study-related is found.

    Result: {"subject": str, "studied": [topic], "understood": [topic],
             "difficult": [(topic, difficulty 2-5)]}
    """
    subject = detect_subject(text)
    clauses = [c.strip() for c in re.split(r"[.;,!\n]|\bbut\b|\bhowever\b", text, flags=re.I) if c.strip()]
    studied, understood, difficult = [], [], []

    for clause in clauses:
        low = clause.lower().strip()
        low = re.sub(r"^(?:and|also|then|though|although)\s+", "", low)
        low = re.sub(r"^i\s+", "", low) if re.match(r"^i\s+(?:find|found)", low) is None else low
        matched = False
        for pat in _DIFFICULT_PATTERNS:
            m = re.search(pat, low)
            if m:
                topic = _strip_subject(_clean(m.group("t")), subject)
                topic = re.sub(r"^(?:i|it|this|that)$", "", topic)
                if topic:
                    level = 5 if any(w in low for w in _INTENSIFIERS) else 4
                    difficult.append((topic, level))
                matched = True
                break
        if matched:
            continue
        for pat in _UNDERSTOOD_PATTERNS:
            m = re.search(pat, low)
            if m:
                topic = _strip_subject(_clean(m.group("t")), subject)
                if topic and topic != "it":
                    understood.append(topic)
                matched = True
                break
        if matched:
            continue
        m = re.search(_STUDIED_PATTERN, low)
        if m:
            topic = _strip_subject(_clean(m.group("t")), subject)
            if topic:
                studied.append(topic)

    # Dedupe, keeping order. A topic that is understood/difficult is not also "studied".
    def uniq(seq):
        seen, out = set(), []
        for x in seq:
            k = x[0] if isinstance(x, tuple) else x
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out

    difficult, understood, studied = uniq(difficult), uniq(understood), uniq(studied)
    dnames = {t for t, _ in difficult}
    understood = [t for t in understood if t not in dnames]
    taken = dnames | set(understood)
    studied = [t for t in studied if t not in taken]

    if not (studied or understood or difficult):
        return None
    if not subject:
        subject = "General"
    return {"subject": subject, "studied": studied, "understood": understood, "difficult": difficult}


def detect_intent(text: str) -> str:
    low = text.lower()
    if re.search(r"what (?:should|do|can) i (?:study|revise|review|learn|do|work on)|study next|revise next|recommend|what next|what to (?:study|revise)|suggest", low):
        return "recommend"
    if re.search(r"what do you remember|show (?:my )?(?:history|memory|memories|progress)|my (?:history|weak|progress)|what have i (?:studied|done)", low):
        return "memory"
    return "record"


def build_recommendation(weak: list[dict], understood: list[dict], recent: list[dict],
                         related: dict[str, list[str]] | None = None) -> dict | None:
    """Rule-based recommendation built ONLY from retrieved graph data.

    Returns None when there is no study history at all.
    """
    related = related or {}
    if weak:
        top = weak[0]
        reason = (f"You reported difficulty with **{top['topic']}** in {top['subject']} "
                  f"(difficulty {top['difficulty']}/5, reported {top['reports']} time(s)).")
        links = related.get(top["topic"], [])
        if links:
            reason += f" You already understand {', '.join(links)} in the same subject, so build on that."
        return _plan(top["topic"], top["subject"], reason, kind="weak")
    if recent:
        oldest = recent[-1]
        reason = (f"No difficult topics are recorded. Your oldest recent session covered "
                  f"**{oldest['topic']}** ({oldest['subject']}); a quick review helps retention.")
        return _plan(oldest["topic"], oldest["subject"], reason, kind="review")
    return None


def _plan(topic: str, subject: str, reason: str, kind: str) -> dict:
    minutes = 15 if kind == "weak" else 10
    return {
        "topic": topic, "subject": subject, "reason": reason, "kind": kind,
        "plan": [
            f"Spend {minutes} minutes re-reading notes or a tutorial on {topic}.",
            f"Work through one fully solved example of {topic}, explaining each step aloud.",
            f"Solve five practice questions on {topic} without looking at the solution.",
            "Record a new study session here to update your memory graph.",
        ],
        "questions": [
            f"Explain {topic} in your own words in two sentences.",
            f"Write a small {subject} example that uses {topic}.",
            f"What is a common mistake when working with {topic}, and how do you avoid it?",
            f"Modify your example so it handles an edge case of {topic}.",
            f"How does {topic} relate to other {subject} topics you know?",
        ],
    }


def format_recommendation_markdown(rec: dict) -> str:
    plan = "\n".join(f"{i}. {s}" for i, s in enumerate(rec["plan"], 1))
    qs = "\n".join(f"- {q}" for q in rec["questions"])
    return (f"### Recommended next: {rec['topic'].title()} ({rec['subject']})\n\n"
            f"**Why (from your graph memory):** {rec['reason']}\n\n"
            f"**Study plan**\n{plan}\n\n**Practice questions**\n{qs}")


def summarize_parsed(parsed: dict) -> str:
    parts = [f"Subject: **{parsed['subject']}**"]
    if parsed["studied"]:
        parts.append("Studied: " + ", ".join(parsed["studied"]))
    if parsed["understood"]:
        parts.append("Understood: " + ", ".join(parsed["understood"]))
    if parsed["difficult"]:
        parts.append("Difficult: " + ", ".join(t for t, _ in parsed["difficult"]))
    return "  \n".join(parts)


DEMO_REPORTS = [
    "I studied Python loops today. I understand for loops, but nested loops are difficult for me.",
    "I studied Python functions. I understand defining functions, but recursion is very confusing.",
]
