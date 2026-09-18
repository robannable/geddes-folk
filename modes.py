"""Cognitive modes — survey, synthesis, proposition.

Carried over from Geddes-Ghost's `GeddesCognitiveModes`. The keyword
scorer and prompt prefixes are unchanged; what could not come across is
the temperature mapping.

Geddes-Ghost varied `temperature` per mode (survey 0.7, synthesis 0.8,
proposition 0.9). `temperature`, `top_p` and `top_k` are rejected with a
400 on every current model, so the dial is gone. The nearest equivalent
is `output_config.effort`, which governs how much the model thinks
before answering rather than how randomly it samples — a coarser, five-
position control that trades thoroughness against token spend.

The guidance paragraphs appended to the character prompt survive
unchanged. They were always doing more of the work than the sampling
parameter was: telling Geddes to "venture into bold speculation" shapes
the prose whatever the sampler is doing.
"""

from dataclasses import dataclass

# Effort levels accepted by the voice model, cheapest first. Haiku 4.5
# rejects `effort` entirely, which is why the classifier call in app.py
# doesn't send one.
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

AUTO = "auto"


@dataclass(frozen=True)
class Mode:
    name: str
    keywords: tuple[str, ...]
    prompt_prefix: str
    effort: str
    guidance: str


MODES: tuple[Mode, ...] = (
    Mode(
        name="survey",
        keywords=(
            "what", "describe", "analyze", "analyse", "observe", "examine",
            "study", "investigate", "explore", "map", "document", "record",
            "measure", "identify", "catalogue", "survey", "inspect", "review",
            "assess", "where", "when", "who", "which", "look", "find",
            "discover",
        ),
        prompt_prefix="Let us first survey and observe...",
        effort="medium",
        guidance=(
            "In this moment, focus on diagnostic precision and careful "
            "observation. Be economical with words and deliberate in your "
            "analysis. The question calls for observation and diagnosis."
        ),
    ),
    Mode(
        name="synthesis",
        keywords=(
            "how", "connect", "relate", "integrate", "combine", "synthesize",
            "synthesise", "weave", "blend", "merge", "link", "bridge", "join",
            "unite", "pattern", "relationship", "network", "system",
            "structure", "framework", "together", "between", "across",
            "through", "interconnect", "associate", "correlate",
        ),
        prompt_prefix="Now, let us weave together these disparate threads...",
        effort="high",
        guidance=(
            "Respond with your natural voice, balancing observation with "
            "interpretation as the question warrants. The question invites "
            "connection-making across domains."
        ),
    ),
    Mode(
        name="proposition",
        keywords=(
            "why", "propose", "suggest", "could", "might", "imagine",
            "envision", "create", "design", "develop", "innovate",
            "transform", "improve", "enhance", "advance", "future",
            "potential", "possible", "alternative", "solution", "strategy",
            "plan", "vision", "hypothesis", "theory", "concept",
        ),
        prompt_prefix="Let us venture forth with a proposition...",
        effort="xhigh",
        guidance=(
            "In this moment, allow yourself to venture into bold speculation "
            "and unexpected connections. Let the response breathe and expand "
            "where the ideas demand it. Embrace creative risk. The question "
            "opens space for speculative intervention."
        ),
    ),
)

BY_NAME = {m.name: m for m in MODES}
DEFAULT = BY_NAME["survey"]


def detect(prompt: str) -> Mode:
    """Pick a mode by keyword scoring, defaulting to survey.

    Whole-word matches score 1, substring matches 0.5 — so "reconnect"
    counts toward synthesis, but less than "connect" does. Ties go to
    survey, which is the least committal of the three.

    Known collision, inherited and left alone: "survey", "plan",
    "pattern" and "design" are mode keywords *and* central Geddes terms,
    so a question about his diagnostic survey scores toward survey mode
    whatever it actually asks. "What is the relationship between the
    survey and the plan?" ties at 2-2 and resolves to survey. The
    scorer is crude on purpose; if the logs show modes consistently
    misread, prune the keyword lists before adding machinery.
    """
    lowered = f" {prompt.lower()} "
    best = DEFAULT
    best_score = -1.0
    for mode in MODES:
        score = 0.0
        for kw in mode.keywords:
            if f" {kw} " in lowered:
                score += 1.0
            elif kw in lowered:
                score += 0.5
        # Strict > keeps the first mode in MODES order on a tie, and
        # survey is first.
        if score > best_score:
            best, best_score = mode, score
    return best


def resolve(prompt: str, override: str = AUTO) -> tuple[Mode, str, str]:
    """Return (mode, effort, source) for a turn.

    `override` is AUTO, or one of EFFORT_LEVELS chosen by the user in the
    chat settings. An override replaces the effort level but not the
    mode — the prompt prefix and guidance still follow from what was
    asked, which is the half of the mechanism that shapes the prose.
    """
    mode = detect(prompt)
    if override in EFFORT_LEVELS:
        return mode, override, "manual"
    return mode, mode.effort, f"auto ({mode.name})"
