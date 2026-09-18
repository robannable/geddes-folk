"""Geddes-Folk: a conversation with Patrick Geddes.

Two voices share the chat:
  - Patrick Geddes himself, re-animated and self-aware.
  - The Librarian, a contemporary archivist who checks what Geddes
    claims and supplies what he leaves out. Invoked explicitly via the
    action on Geddes's replies, or automatically when the classifier
    says a turn needs it.

The classifier returns one of three verdicts rather than a boolean:
CHECK (Geddes made a checkable claim), CONTEXT (contested ground), or
SKIP. Both firing verdicts are logged so false positives can be tuned
per track — the cost of running two trigger sets instead of one.

Retrieval is wired to `retrieval.Retriever` over a FAISS index built by
`ingest.py`. When the index isn't present, both voices speak from their
prompts alone.
"""

import asyncio
from pathlib import Path

import chainlit as cl
from anthropic import AsyncAnthropic
from chainlit.input_widget import Select, TextInput
from dotenv import load_dotenv

import dashboard
import modes
from config import (
    CLASSIFIER_MODEL,
    GEDDES,
    LIBRARIAN,
    RETRIEVE_K,
    VOICE_MODEL,
    label,
)
from retrieval import Retriever, format_for_prompt
from session_log import chunk_meta, cost_cents, log_turn, usage_to_dict

load_dotenv()

ROOT = Path(__file__).parent
PROMPTS = ROOT / "prompts"

GEDDES_PERSONA = (PROMPTS / "patrick_geddes_persona.txt").read_text(encoding="utf-8")
LIBRARIAN_VOICE = (PROMPTS / "librarian_voice.txt").read_text(encoding="utf-8")

client = AsyncAnthropic()
retriever = Retriever()

# Serve the conversation dashboard at /dashboard on this same server.
# Returns False and prints if Chainlit's internals have moved; the chat
# app starts either way.
DASHBOARD_MOUNTED = dashboard.mount()

# Verdicts the classifier may return. SKIP means the Librarian stays out.
CHECK = "CHECK"
CONTEXT = "CONTEXT"
SKIP = "SKIP"


# --- retrieval --------------------------------------------------------


async def retrieve_context(
    query: str, voice: str, user: str
) -> tuple[str, list[dict]]:
    """Retrieve corpus passages for `query` visible to `voice` and `user`.

    Returns (formatted_prompt_text, raw_chunks). The first is injected
    into the user message; the second is kept for logging. Both are
    empty when the index hasn't been built — the voice then speaks from
    its prompt alone, which is the behaviour while the corpus is being
    prepared. A foldable step surfaces what was retrieved, labelled by
    voice so the two retrievals are distinguishable in the chat.
    """
    if not retriever.ready:
        return "", []
    chunks = await asyncio.to_thread(
        retriever.search, query, RETRIEVE_K, voice, user
    )
    formatted = format_for_prompt(chunks)
    if chunks:
        name = GEDDES if voice == "geddes" else LIBRARIAN
        async with cl.Step(
            name=f"{name} retrieved {len(chunks)} passage(s)", type="retrieval"
        ) as step:
            step.input = query
            step.output = formatted
    return formatted, chunks


# --- classifier -------------------------------------------------------


CLASSIFIER_INSTRUCTION = """You triage a conversation between Patrick Geddes \
(1854-1932, re-animated as a chatbot persona) and a student. You decide \
whether a contemporary archivist — "the Librarian" — should interject after \
Geddes's response, and on which of two grounds.

Reply with exactly one word on the first line: CHECK, CONTEXT, or SKIP.

CHECK — Geddes made a specific factual claim that could be verified or \
falsified, and that a student might carry away and rely on. Examples: he \
named a book, paper, author or thinker; he gave a date, a figure, a \
population, a dimension; he quoted someone; he attributed an idea to a named \
person; he asserted a specific historical event or sequence. The persona is \
built to reason abductively toward unexpected conclusions, so it \
manufactures plausible attributions — this is the common case, and a \
borderline claim is worth CHECK.

Do NOT return CHECK for: his own convictions and method stated as his own \
(the valley section, conservative surgery, Folk-Work-Place, the diagnostic \
survey); general characterisations of a field or debate with no named source; \
claims he has already explicitly marked as uncertain recollection.

CONTEXT — the exchange touches ground the intervening century has contested, \
and a student is owed what Geddes leaves out:
- His town planning reports for Indian municipalities and princely states, \
written under British paramountcy, and the politics of planning for a \
colonial administration.
- His work for the Zionist Commission and the 1925 Tel Aviv plan.
- The sexual science of The Evolution of Sex (1889, with J. Arthur Thomson) — \
the anabolic/katabolic theory — and its use against women's suffrage and \
women's higher education.
- Paternalism toward slum populations and the poor; who decided what \
"improvement" meant.
- Eugenic or social-Darwinist framing, and the later uses made of his ideas \
by planners and regimes after his death.

SKIP — neither applies. Uncontested method, his own biography in neutral \
terms, a general discussion of ideas with nothing checkable in it, or a \
conversational exchange. SKIP is a common and correct answer; the Librarian \
interjecting on neutral material is a failure, not a safety margin.

If both would apply, return CONTEXT — it is the harder thing to leave unsaid.

STUDENT ASKED:
{user_msg}

GEDDES RESPONDED:
{geddes_response}"""


async def classify_librarian_trigger(
    user_msg: str, geddes_response: str
) -> tuple[str, object]:
    """Return (verdict, usage). Verdict is CHECK, CONTEXT or SKIP.

    Haiku 4.5 rejects `output_config.effort`, so this call sends neither
    effort nor adaptive thinking — it's a cheap three-way string
    classification and doesn't want either.
    """
    response = await client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=16,
        messages=[{
            "role": "user",
            "content": CLASSIFIER_INSTRUCTION.format(
                user_msg=user_msg, geddes_response=geddes_response
            ),
        }],
    )
    text = next(
        (b.text for b in response.content if b.type == "text"), ""
    ).strip().upper()
    if text.startswith(CHECK):
        verdict = CHECK
    elif text.startswith(CONTEXT):
        verdict = CONTEXT
    else:
        verdict = SKIP
    return verdict, response.usage


# --- voices -----------------------------------------------------------


async def stream_geddes(
    user_msg: str,
    user_name: str,
    history: list[dict],
    context: str,
    mode: modes.Mode,
    effort: str,
) -> tuple[str, object]:
    """Stream Geddes's reply into a Chainlit message; return (text, usage)."""
    msg = cl.Message(content="", author=GEDDES)
    await msg.send()

    parts = []
    if context:
        parts.append(
            f"[Passages from your own writings and the studio's material, "
            f"for grounding]\n{context}\n"
        )
    parts.append(f"{user_name} asks: {user_msg}")
    framed_user = "\n".join(parts)

    # Two system blocks, and the order matters. Caching is a prefix match,
    # so the breakpoint goes after the persona — which never changes —
    # and the mode guidance sits in a second, uncached block after it.
    # Concatenating the two would change the cached prefix every time the
    # mode changed and thrash the cache three ways.
    system_blocks = [
        {
            "type": "text",
            "text": GEDDES_PERSONA,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                f"{mode.guidance}\n\n"
                f"You might open in the spirit of: \"{mode.prompt_prefix}\" — "
                f"though only if it suits; do not use it as a formula."
            ),
        },
    ]

    api_messages = history[:-1] + [{"role": "user", "content": framed_user}]

    chunks: list[str] = []
    async with client.messages.stream(
        model=VOICE_MODEL,
        max_tokens=4000,
        system=system_blocks,
        messages=api_messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    ) as stream:
        async for text in stream.text_stream:
            chunks.append(text)
            await msg.stream_token(text)
        final = await stream.get_final_message()

    full = "".join(chunks)

    msg.actions = [cl.Action(
        name="ask_librarian",
        payload={"user_msg": user_msg, "geddes_response": full},
        label="Ask the Librarian",
        tooltip=(
            "Check the references, or ask for the scholarly context behind "
            "what Geddes just said"
        ),
    )]
    await msg.update()

    return full, final.usage


LIBRARIAN_FRAMINGS = {
    CHECK: (
        "Geddes has made one or more checkable claims — a named work, "
        "person, date, figure, or quotation. Check them against the "
        "passages below and what you hold. Confirm precisely what checks "
        "out, correct what is wrong, and say plainly where you cannot "
        "confirm something rather than implying you can. Keep it to a "
        "short paragraph and return the floor to him."
    ),
    CONTEXT: (
        "The exchange has reached contested ground. Interject briefly — a "
        "short paragraph — to supply what a student needs in order to "
        "judge: the relevant scholarship, the historical circumstances "
        "Geddes passes over, and the case on both sides where there is "
        "one. Do not rewrite his answer; supply what he didn't, then "
        "return the floor to him."
    ),
    "explicit": (
        "The student has asked you directly. Give them what serves them "
        "best — the references with their sources, the fuller "
        "bibliography, the archival location, the state of the scholarly "
        "argument, or what to read next. Be substantive but concise."
    ),
}


async def stream_librarian(
    user_msg: str,
    geddes_response: str,
    context: str,
    trigger: str,
) -> tuple[str, object]:
    """Stream the Librarian's reply; return (text, usage).

    `trigger` is CHECK, CONTEXT, or "explicit".
    """
    framing = (
        f"The student asked Patrick Geddes the question below, and he has "
        f"given the response below. "
        f"{LIBRARIAN_FRAMINGS.get(trigger, LIBRARIAN_FRAMINGS['explicit'])}"
        f"\n\nSTUDENT QUESTION:\n{user_msg}"
        f"\n\nGEDDES'S RESPONSE:\n{geddes_response}"
    )
    if context:
        framing += f"\n\nRELEVANT PASSAGES FROM THE CORPUS:\n{context}"
    else:
        framing += (
            "\n\n(No corpus passages were retrieved for this turn — the "
            "index may not be built. Be correspondingly careful to mark "
            "what you are recalling rather than checking.)"
        )

    msg = cl.Message(content="", author=LIBRARIAN)
    await msg.send()

    chunks: list[str] = []
    async with client.messages.stream(
        model=VOICE_MODEL,
        max_tokens=2000,
        system=[{
            "type": "text",
            "text": LIBRARIAN_VOICE,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": framing}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
    ) as stream:
        async for text in stream.text_stream:
            chunks.append(text)
            await msg.stream_token(text)
        final = await stream.get_final_message()

    await msg.update()
    return "".join(chunks), final.usage


# --- session ----------------------------------------------------------


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("history", [])
    cl.user_session.set("user_name", "")
    cl.user_session.set("session_cents", 0.0)

    await cl.ChatSettings([
        TextInput(
            id="user_name",
            label="Your name",
            initial="",
            description=(
                "Used to address you, and to surface your own uploaded work "
                "from the corpus ahead of the general material."
            ),
        ),
        Select(
            id="effort",
            label="Effort",
            values=[modes.AUTO] + modes.EFFORT_LEVELS,
            initial_index=0,
            description=(
                "Auto picks effort from the kind of question asked — survey "
                "medium, synthesis high, proposition xhigh. Override to fix "
                "it. (Replaces the temperature slider: current models "
                "reject temperature.)"
            ),
        ),
    ]).send()

    await cl.Message(
        content=(
            "Greetings, dear inquirer! I am Patrick Geddes — biologist, "
            "sociologist, geographer, and something of a revolutionary in "
            "the matter of town planning, if I do say so myself.\n\n"
            "Set your name in the settings panel — the slider beside the "
            "message box — and I shall address you properly; your own work, "
            "if any of it sits in our archive, will come to hand first. Then "
            "tell me what question about our shared world we shall explore "
            "together. The Librarian sits with us "
            "and holds the archive — it will speak when I have said "
            "something that wants checking, or when the conversation "
            "reaches ground I cannot fairly cover alone. You may summon it "
            "yourself with the button beneath any of my replies.\n\n"
            "*By leaves we live* — so let your curiosity bloom, and ask away."
        ),
        author=GEDDES,
    ).send()

    if DASHBOARD_MOUNTED:
        # Tutor-facing, so it sits in a folded step rather than in
        # Geddes's voice.
        async with cl.Step(name="Conversation dashboard", type="tool") as step:
            step.output = (
                "Retrieval health, Librarian trigger rates, cost and corpus "
                "usage across every logged turn: "
                "[/dashboard](/dashboard)\n\n"
                "Reads `logs/*.jsonl` live — reload it for the current state."
            )


@cl.on_settings_update
async def on_settings_update(settings: dict):
    cl.user_session.set("user_name", (settings.get("user_name") or "").strip())
    cl.user_session.set("effort", settings.get("effort") or modes.AUTO)


def _dedupe(chunks: list[dict]) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for c in chunks:
        cid = c.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


@cl.on_message
async def on_message(message: cl.Message):
    user_name = cl.user_session.get("user_name") or "A student"
    override = cl.user_session.get("effort") or modes.AUTO

    history: list[dict] = cl.user_session.get("history") or []
    history.append({"role": "user", "content": message.content})

    mode, effort, effort_source = modes.resolve(message.content, override)

    geddes_context, geddes_chunks = await retrieve_context(
        message.content, "geddes", user_name
    )

    geddes_text, geddes_usage = await stream_geddes(
        message.content, user_name, history, geddes_context, mode, effort
    )
    history.append({"role": "assistant", "content": geddes_text})
    cl.user_session.set("history", history)

    verdict, classifier_usage = await classify_librarian_trigger(
        message.content, geddes_text
    )

    librarian_record = None
    lib_chunks: list[dict] = []
    if verdict != SKIP:
        lib_context, lib_chunks = await retrieve_context(
            message.content, "librarian", user_name
        )
        lib_text, lib_usage = await stream_librarian(
            message.content, geddes_text, lib_context, verdict
        )
        librarian_record = {
            "trigger": verdict.lower(),
            "text": lib_text,
            "usage": usage_to_dict(lib_usage),
        }

    await _emit_log(
        kind="turn",
        user_name=user_name,
        user_msg=message.content,
        mode={"name": mode.name, "effort": effort, "source": effort_source},
        context_chunks=_dedupe(geddes_chunks + lib_chunks),
        geddes={"text": geddes_text, "usage": usage_to_dict(geddes_usage)},
        classifier={
            "verdict": verdict,
            "usage": usage_to_dict(classifier_usage),
        },
        librarian=librarian_record,
    )


@cl.action_callback("ask_librarian")
async def on_ask_librarian(action: cl.Action):
    payload = action.payload or {}
    user_msg = payload.get("user_msg", "")
    geddes_response = payload.get("geddes_response", "")
    user_name = cl.user_session.get("user_name") or "A student"

    lib_context, lib_chunks = await retrieve_context(
        user_msg, "librarian", user_name
    )
    lib_text, lib_usage = await stream_librarian(
        user_msg, geddes_response, lib_context, "explicit"
    )
    await _emit_log(
        kind="librarian_explicit",
        user_name=user_name,
        user_msg=user_msg,
        mode=None,
        context_chunks=lib_chunks,
        geddes={"text": geddes_response, "usage": None},
        classifier=None,
        librarian={
            "trigger": "explicit",
            "text": lib_text,
            "usage": usage_to_dict(lib_usage),
        },
    )


# --- logging ----------------------------------------------------------


async def _emit_log(
    kind: str,
    user_name: str,
    user_msg: str,
    mode: dict | None,
    context_chunks: list[dict],
    geddes: dict,
    classifier: dict | None,
    librarian: dict | None,
) -> None:
    """Write a turn record to JSONL, print a console summary, and surface
    a foldable Tokens step in the UI."""
    geddes_cents = cost_cents(VOICE_MODEL, geddes.get("usage"))
    classifier_cents = (
        cost_cents(CLASSIFIER_MODEL, classifier["usage"]) if classifier else 0.0
    )
    librarian_cents = (
        cost_cents(VOICE_MODEL, librarian["usage"]) if librarian else 0.0
    )
    turn_cents = geddes_cents + classifier_cents + librarian_cents

    session_cents = (cl.user_session.get("session_cents") or 0.0) + turn_cents
    cl.user_session.set("session_cents", session_cents)

    log_turn({
        "kind": kind,
        "user_name": user_name,
        "user": user_msg,
        "mode": mode,
        "context_chunks": [chunk_meta(c) for c in context_chunks],
        "geddes": geddes,
        "classifier": classifier,
        "librarian": librarian,
        "cost_cents": {
            "geddes": round(geddes_cents, 4),
            "classifier": round(classifier_cents, 4),
            "librarian": round(librarian_cents, 4),
            "turn_total": round(turn_cents, 4),
            "session_total": round(session_cents, 4),
        },
    })

    voice_label = label(VOICE_MODEL)
    clf_label = label(CLASSIFIER_MODEL)

    console: list[str] = []
    lines: list[str] = []
    if geddes.get("usage"):
        u = geddes["usage"]
        console.append(f"geddes {u['in']}→{u['out']}")
        lines.append(
            f"- Geddes ({voice_label}): {u['in']} in / {u['out']} out"
            f"  ≈{geddes_cents:.3f}¢"
        )
    if classifier:
        u = classifier["usage"]
        console.append(f"classifier {u['in']}→{u['out']} {classifier['verdict']}")
        lines.append(
            f"- Classifier ({clf_label}): {u['in']} in / {u['out']} out  "
            f"verdict={classifier['verdict']}  ≈{classifier_cents:.3f}¢"
        )
    if librarian:
        u = librarian["usage"]
        console.append(f"librarian {u['in']}→{u['out']}")
        lines.append(
            f"- Librarian ({voice_label}, {librarian['trigger']}): "
            f"{u['in']} in / {u['out']} out  ≈{librarian_cents:.3f}¢"
        )
    if mode:
        lines.append(
            f"- Mode: {mode['name']}, effort {mode['effort']} ({mode['source']})"
        )
    lines.append(f"- **Turn total: ≈{turn_cents:.3f}¢**")
    lines.append(f"- Session so far: ≈{session_cents:.2f}¢")

    mode_note = f" [{mode['name']}/{mode['effort']}]" if mode else ""
    print(
        f"[{kind}]{mode_note} " + "  ".join(console) +
        f"  ≈{turn_cents:.3f}¢  session≈{session_cents:.2f}¢"
    )

    async with cl.Step(
        name=f"Tokens · ≈{turn_cents:.2f}¢ (session ≈{session_cents:.2f}¢)",
        type="tool",
    ) as step:
        step.output = "\n".join(lines)
