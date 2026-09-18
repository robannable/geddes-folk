"""Render logs/*.jsonl as a self-contained HTML report.

    python dashboard.py                  # all logs -> logs/dashboard.html
    python dashboard.py --days 14        # last 14 days only
    python dashboard.py --out report.html

No dependencies beyond the standard library, and no server: the output is
one HTML file with inline SVG charts and no external requests, so it opens
from disk, over a file share, on a phone, or from the VPS.

Geddes-Ghost's `admin_dashboard.py` was a 1,200-line Streamlit app whose
`ResponseEvaluator` the chat app then imported back out of it. This reads
the JSONL and writes a file; nothing imports it and it imports nothing
from the app.

Its temperature analysis has no successor here — temperature is rejected
by current models, so there is no continuous dial to plot response length
against. The cognitive-mode panel is the nearest honest equivalent.
"""

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
LOGS = ROOT / "logs"

# --- palette ---------------------------------------------------------------
# Three categorical slots from the validated default palette, in fixed
# order. Validated all-pairs in both modes (worst CVD dE 9.2 light / 9.4
# dark; worst normal-vision dE 24.0 light / 20.9 dark). Aqua sits below
# 3:1 on the light surface, so every chart carries a legend, direct
# labels and the table view at the foot of the page — the relief rule.
# Adding a fourth slot would put yellow beside orange and fail all-pairs;
# fold to "other" instead.
SERIES = ("var(--series-1)", "var(--series-2)", "var(--series-3)")

VERDICTS = ("CHECK", "CONTEXT", "SKIP")
VOICES = ("geddes", "classifier", "librarian")
MODE_ORDER = ("survey", "synthesis", "proposition")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over",
    "about", "your", "their", "when", "what", "why", "are", "was", "were",
    "will", "would", "could", "should", "have", "has", "had", "you", "our",
    "how", "does", "did", "can", "its", "but", "not", "any", "all", "more",
    "some", "such", "than", "then", "them", "they", "there", "here", "been",
    "being", "which", "who", "whom", "his", "her", "hers", "him", "she",
    "please", "tell", "think", "know", "like", "just", "really", "also",
}


# --- loading ---------------------------------------------------------------


def load(days: int | None = None) -> list[dict]:
    """Read every logs/*.jsonl, newest last. Malformed lines are skipped."""
    turns: list[dict] = []
    if not LOGS.exists():
        return turns
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for path in sorted(LOGS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts")
            if not ts:
                continue
            try:
                when = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if cutoff and when < cutoff:
                continue
            rec["_when"] = when
            rec["_day"] = when.strftime("%Y-%m-%d")
            turns.append(rec)
    turns.sort(key=lambda r: r["_when"])
    return turns


# --- small helpers ---------------------------------------------------------


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def money(cents: float) -> str:
    """Cents below a pound, pounds above — a session costs pennies."""
    if cents >= 100:
        return f"£{cents / 100:.2f}"
    return f"{cents:.2f}p"


def words(text: str) -> int:
    return len((text or "").split())


def _rounded_top(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Path for a rect with only its top corners rounded (the data end)."""
    r = min(r, w / 2, h)
    return (
        f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"V{y + h:.1f} Z"
    )


def _axis(v: float, integer: bool) -> tuple[float, int]:
    """Return (max, tick_count) giving round tick values.

    Counts get integer ticks — an axis reading 1.875 on a bar chart of
    whole turns is noise. Picks the first step on a nice ladder that
    covers the data in at most five gridlines.
    """
    if v <= 0:
        return (4.0, 4) if integer else (1.0, 4)
    ladder = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
    if not integer:
        ladder = [0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100]
    for step in ladder:
        for n in (4, 5, 3):
            if step * n >= v:
                return float(step * n), n
    return float(v), 4


# --- chart primitives ------------------------------------------------------


def legend(labels: list[str]) -> str:
    items = "".join(
        f'<span class="key"><i style="background:{SERIES[i % len(SERIES)]}"></i>'
        f"{esc(l)}</span>"
        for i, l in enumerate(labels)
    )
    return f'<div class="legend">{items}</div>'


def bar_h(rows: list[tuple[str, float, str]], fmt=lambda v: f"{v:g}",
          slot: int = 0, per_row: bool = False) -> str:
    """Horizontal bars: rows of (label, value, tooltip).

    One series by default, so no legend — the panel title names it. Every
    bar is directly labelled with its value, which is also the relief the
    light-mode contrast warning requires.

    `per_row` colours each row from its own slot instead. Use it only when
    the rows are entities another chart on the page already colours, so
    identity stays attached to the thing rather than to the row position.
    """
    if not rows:
        return '<p class="empty">No data yet.</p>'
    top = max(v for _, v, _ in rows) or 1
    out = []
    for i, (label, value, tip) in enumerate(rows):
        pct = 100 * value / top
        colour = SERIES[(i if per_row else slot) % len(SERIES)]
        out.append(
            f'<div class="hrow" data-tip="{esc(tip)}">'
            f'<div class="hlabel">{esc(label)}</div>'
            f'<div class="htrack"><div class="hbar" style="width:{pct:.1f}%;'
            f"background:{colour}\"></div></div>"
            f'<div class="hval">{esc(fmt(value))}</div>'
            f"</div>"
        )
    return f'<div class="hbars">{"".join(out)}</div>'


def bar_stacked(days: list[str], series: dict[str, list[float]],
                fmt=lambda v: f"{v:g}", unit: str = "",
                integer: bool = True) -> str:
    """Stacked vertical bars over days. `series` is name -> per-day values.

    2px surface gap between segments, 4px rounded top on the data end,
    total directly labelled above each stack, recessive gridlines.
    """
    names = list(series)
    if not days or not names:
        return '<p class="empty">No data yet.</p>'

    totals = [sum(series[n][i] for n in names) for i in range(len(days))]
    ymax, nticks = _axis(max(totals) if totals else 1, integer)

    pad_l, pad_r, pad_t, pad_b = 46, 12, 22, 34
    plot_w, plot_h = 640, 200
    w, h = pad_l + plot_w + pad_r, pad_t + plot_h + pad_b
    slot = plot_w / max(len(days), 1)
    bw = min(38.0, slot * 0.62)

    parts = [
        f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" '
        f'preserveAspectRatio="xMidYMid meet">'
    ]

    # Gridlines and y axis — recessive.
    for i in range(nticks + 1):
        v = ymax * i / nticks
        y = pad_t + plot_h - (plot_h * i / nticks)
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{y:.1f}" '
            f'x2="{pad_l + plot_w}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{pad_l - 8}" y="{y + 4:.1f}" '
            f'text-anchor="end">{esc(fmt(v))}</text>'
        )

    for i, day in enumerate(days):
        x = pad_l + slot * i + (slot - bw) / 2
        y_cursor = pad_t + plot_h
        stack_total = totals[i]
        # Draw bottom-up so the last drawn segment is the data end.
        drawn = []
        for si, name in enumerate(names):
            v = series[name][i]
            if v <= 0:
                continue
            seg_h = (v / ymax) * plot_h if ymax else 0
            if seg_h < 0.6:
                continue
            y_cursor -= seg_h
            drawn.append((si, name, v, y_cursor, seg_h))
        for idx, (si, name, v, y, seg_h) in enumerate(drawn):
            colour = SERIES[si % len(SERIES)]
            tip = f"{day} · {name}: {fmt(v)}{unit}"
            # 2px surface gap between segments; top segment gets the
            # rounded data end. A segment thinner than the gap keeps its
            # full height — a hairline classifier cost is real and should
            # still be visible.
            gap = 2 if (idx < len(drawn) - 1 and seg_h > 5) else 0
            if idx == len(drawn) - 1:
                parts.append(
                    f'<path d="{_rounded_top(x, y, bw, max(seg_h - gap, 1))}" '
                    f'fill="{colour}" data-tip="{esc(tip)}"/>'
                )
            else:
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                    f'height="{max(seg_h - gap, 1):.1f}" fill="{colour}" '
                    f'data-tip="{esc(tip)}"/>'
                )
        if stack_total > 0:
            top_y = pad_t + plot_h - (stack_total / ymax) * plot_h
            parts.append(
                f'<text class="dlabel" x="{x + bw / 2:.1f}" '
                f'y="{max(top_y - 6, 10):.1f}" text-anchor="middle">'
                f"{esc(fmt(stack_total))}</text>"
            )

    # X labels — thinned so they never collide.
    every = max(1, len(days) // 12 + 1)
    for i, day in enumerate(days):
        if i % every:
            continue
        x = pad_l + slot * i + slot / 2
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{pad_t + plot_h + 18}" '
            f'text-anchor="middle">{esc(day[5:])}</text>'
        )

    parts.append(
        f'<line class="axis" x1="{pad_l}" y1="{pad_t + plot_h}" '
        f'x2="{pad_l + plot_w}" y2="{pad_t + plot_h}"/>'
    )
    parts.append("</svg>")
    return legend(names) + "".join(parts)


def tiles(items: list[tuple[str, str, str]]) -> str:
    cells = "".join(
        f'<div class="tile"><div class="tval">{esc(v)}</div>'
        f'<div class="tlab">{esc(label)}</div>'
        f'<div class="tsub">{esc(sub)}</div></div>'
        for label, v, sub in items
    )
    return f'<div class="tiles">{cells}</div>'


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    if not rows:
        return '<p class="empty">No data yet.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows
    )
    return (
        f'<div class="tablewrap"><table class="{cls}"><thead><tr>{head}</tr>'
        f"</thead><tbody>{body}</tbody></table></div>"
    )


def panel(title: str, note: str, body: str) -> str:
    n = f'<p class="note">{note}</p>' if note else ""
    return f"<section><h2>{esc(title)}</h2>{n}{body}</section>"


# --- analysis --------------------------------------------------------------


def analyse(turns: list[dict]) -> dict:
    convo = [t for t in turns if t.get("kind") == "turn"]
    explicit = [t for t in turns if t.get("kind") == "librarian_explicit"]
    days = sorted({t["_day"] for t in turns})

    verdicts = Counter(
        (t.get("classifier") or {}).get("verdict") for t in convo
    )
    verdicts.pop(None, None)

    per_day_verdict = {v: [0.0] * len(days) for v in VERDICTS}
    per_day_cost = {v: [0.0] * len(days) for v in VOICES}
    day_index = {d: i for i, d in enumerate(days)}
    for t in convo:
        v = (t.get("classifier") or {}).get("verdict")
        if v in per_day_verdict:
            per_day_verdict[v][day_index[t["_day"]]] += 1
    for t in turns:
        cost = t.get("cost_cents") or {}
        for voice in VOICES:
            per_day_cost[voice][day_index[t["_day"]]] += cost.get(voice, 0.0) or 0.0

    # Retrieval health. A chunk visible to Geddes is one tagged "geddes"
    # or "both"; the rest only reach the Librarian. This is the check that
    # the corpus is actually reaching the persona.
    grounded = ungrounded = 0
    for t in convo:
        seen = [
            c for c in (t.get("context_chunks") or [])
            if (c.get("voice") or "both") in ("geddes", "both")
        ]
        if seen:
            grounded += 1
        else:
            ungrounded += 1

    # Corpus usage, with the voice split kept — a source only ever
    # retrieved for the Librarian is doing a different job.
    src_hits: Counter = Counter()
    src_scores = defaultdict(list)
    src_voice = defaultdict(set)
    for t in turns:
        for c in t.get("context_chunks") or []:
            title = c.get("source_title") or "?"
            src_hits[title] += 1
            if c.get("score") is not None:
                src_scores[title].append(c["score"])
            src_voice[title].add(c.get("voice") or "both")

    modes = Counter()
    mode_lengths = defaultdict(list)
    efforts = Counter()
    manual = 0
    for t in convo:
        m = t.get("mode") or {}
        if m.get("name"):
            modes[m["name"]] += 1
            mode_lengths[m["name"]].append(
                words((t.get("geddes") or {}).get("text", ""))
            )
        if m.get("effort"):
            efforts[m["effort"]] += 1
        if (m.get("source") or "").startswith("manual"):
            manual += 1

    users = Counter(t.get("user_name") or "—" for t in turns)
    user_cost: Counter = Counter()
    for t in turns:
        user_cost[t.get("user_name") or "—"] += (
            t.get("cost_cents") or {}
        ).get("turn_total", 0.0) or 0.0

    kw = Counter()
    for t in turns:
        for w in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", (t.get("user") or "").lower()):
            if w not in STOPWORDS:
                kw[w] += 1

    total_cost = sum(
        (t.get("cost_cents") or {}).get("turn_total", 0.0) or 0.0 for t in turns
    )

    return {
        "turns": turns, "convo": convo, "explicit": explicit, "days": days,
        "verdicts": verdicts, "per_day_verdict": per_day_verdict,
        "per_day_cost": per_day_cost, "grounded": grounded,
        "ungrounded": ungrounded, "src_hits": src_hits,
        "src_scores": src_scores, "src_voice": src_voice, "modes": modes,
        "mode_lengths": mode_lengths, "efforts": efforts, "manual": manual,
        "users": users, "user_cost": user_cost, "kw": kw,
        "total_cost": total_cost,
    }


# --- panels ----------------------------------------------------------------


def build_panels(a: dict) -> str:
    turns, convo, days = a["turns"], a["convo"], a["days"]
    out = []

    # Overview
    mean = a["total_cost"] / len(turns) if turns else 0
    span = f"{days[0]} to {days[-1]}" if days else "—"
    auto_spoke = sum(1 for t in convo if t.get("librarian"))
    spoke_pct = 100 * auto_spoke / len(convo) if convo else 0
    out.append(panel("Overview", "", tiles([
        ("Conversational turns", str(len(convo)), span),
        ("Librarian spoke",
         f"{spoke_pct:.0f}%",
         f"{auto_spoke} interjections + {len(a['explicit'])} summoned"),
        ("Students", str(len({u for u in a["users"] if u != "—"})),
         f"{a['users'].get('—', 0)} turns with no name set"),
        ("Total cost", money(a["total_cost"]), f"mean {money(mean)} per turn"),
    ])))

    # Retrieval health — the corpus-is-reaching-him check.
    total_c = a["grounded"] + a["ungrounded"]
    pct = 100 * a["grounded"] / total_c if total_c else 0
    health = (
        f'<div class="hero"><div class="hnum">{pct:.0f}%</div>'
        f'<div class="hcap">of turns reached Geddes with at least one '
        f'retrieved passage<br><span class="tsub">'
        f'{a["grounded"]} grounded · {a["ungrounded"]} on the persona '
        f"prompt alone</span></div></div>"
    )
    if total_c and pct < 50:
        health += (
            '<p class="warn">Most turns are ungrounded. Either the index '
            "isn't built (<code>python ingest.py</code>) or the corpus has "
            "nothing tagged <code>voice: geddes</code> / <code>both</code> "
            "on these topics. A fact-checking Librarian over an empty "
            "corpus can only say it cannot confirm.</p>"
        )
    out.append(panel(
        "Retrieval health",
        "Whether the corpus is actually reaching the persona, rather than "
        "being retrieved and discarded. The predecessor failed silently here.",
        health,
    ))

    # Librarian triggers — the two-track tuning surface.
    counts = [
        (v, a["verdicts"].get(v, 0),
         f"{v}: {a['verdicts'].get(v, 0)} of {len(convo)} turns")
        for v in VERDICTS
    ]
    trig = bar_h(counts, fmt=lambda v: f"{v:g}", per_row=True)
    trig += bar_stacked(days, a["per_day_verdict"])
    out.append(panel(
        "Librarian triggers",
        "CHECK fires on a claim that wants verifying; CONTEXT on contested "
        "ground; SKIP means silence. Read the two firing tracks separately — "
        "a CHECK on neutral method and a CONTEXT on an uncontested question "
        "are different faults with different fixes.",
        trig,
    ))

    # Cognitive modes — the honest successor to the temperature tab.
    mrows = []
    for m in MODE_ORDER:
        n = a["modes"].get(m, 0)
        lens = a["mode_lengths"].get(m, [])
        avg = sum(lens) / len(lens) if lens else 0
        mrows.append((m, n, f"{m}: {n} turns, mean reply {avg:.0f} words"))
    mode_body = bar_h(mrows, fmt=lambda v: f"{v:g}")
    mode_body += table(
        ["Mode", "Turns", "Mean reply (words)", "Effort"],
        [[m, str(a["modes"].get(m, 0)),
          f"{(sum(a['mode_lengths'].get(m, [])) / len(a['mode_lengths'][m])):.0f}"
          if a["mode_lengths"].get(m) else "—",
          {"survey": "medium", "synthesis": "high",
           "proposition": "xhigh"}[m]]
         for m in MODE_ORDER],
    )
    out.append(panel(
        "Cognitive modes",
        f"{a['manual']} of {len(convo)} turns used a manual effort override. "
        "Geddes-Ghost plotted response length against temperature; current "
        "models reject temperature, so there is no continuous dial to plot "
        "and this is mode against reply length instead.",
        mode_body,
    ))

    # Cost
    out.append(panel(
        "Cost",
        "Estimated from config.PRICES_USD_PER_MTOK. A voice reading zero "
        "throughout means its model is missing from that table, not that it "
        "was free.",
        bar_stacked(days, a["per_day_cost"], fmt=lambda v: f"{v:.1f}",
                    unit="p", integer=False),
    ))

    # Corpus usage
    rows = []
    for title, n in a["src_hits"].most_common(15):
        scores = a["src_scores"].get(title, [])
        avg = sum(scores) / len(scores) if scores else None
        voices = "/".join(sorted(a["src_voice"].get(title, {"both"})))
        tip = (f"{title}: {n} retrievals, "
               f"mean score {avg:.3f}" if avg is not None else f"{title}: {n}")
        rows.append((title[:52], n, f"{tip} · visible to {voices}"))
    out.append(panel(
        "Corpus usage",
        "Which sources retrieval actually reaches, and how well they score. "
        "A source that never appears is either irrelevant to what is being "
        "asked or badly chunked.",
        bar_h(rows, slot=2),
    ))

    # Students
    urows = [
        (u, n, f"{u}: {n} turns, {money(a['user_cost'][u])}")
        for u, n in a["users"].most_common(15)
    ]
    out.append(panel(
        "Students", "",
        bar_h(urows, slot=1)
        + table(["Student", "Turns", "Cost"],
                [[u, str(n), money(a["user_cost"][u])]
                 for u, n in a["users"].most_common(30)]),
    ))

    # Questions
    krows = [(w, n, f"{w}: {n} occurrences") for w, n in a["kw"].most_common(18)]
    qlens = [words(t.get("user") or "") for t in turns]
    qmean = sum(qlens) / len(qlens) if qlens else 0
    out.append(panel(
        "What is being asked",
        f"Mean question length {qmean:.0f} words. Crude frequency count over "
        "student messages, stopwords removed.",
        bar_h(krows, slot=2),
    ))

    # Interventions — high interest, low grounding.
    sugg = []
    for title, n in a["src_hits"].most_common():
        scores = a["src_scores"].get(title, [])
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        sugg.append((title, n, avg))
    sugg.sort(key=lambda r: (-r[1], r[2]))
    # There is no absolute score that means "well grounded" — similarity
    # scales differ by embedding model and corpus. Compare each source to
    # the median of this set, and say that is what is being compared.
    med = 0.0
    if sugg:
        vals = sorted(s3 for _, _, s3 in sugg)
        mid = len(vals) // 2
        med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    irows = []
    for t, n, avg in sugg[:8]:
        if avg < med:
            reading = ("Below the median for this set — reached often but "
                       "matched weakly. Check the chunking, or add a source "
                       "that covers it properly.")
        else:
            reading = "At or above the median for this set."
        irows.append([t, str(n), f"{avg:.3f}", reading])
    out.append(panel(
        "Interventions",
        f"Sources ranked by how often students reach them. Scores are "
        f"compared to this set's median ({med:.3f}), not to any absolute "
        f"threshold — similarity numbers only mean something relative to "
        f"the same corpus and embedding model. Geddes-Ghost generated a "
        f"teaching plan from these numbers; the scores it used were "
        f"mis-indexed, so this reports them and leaves the judgement to you.",
        table(["Source", "Retrievals", "Mean score", "Against median"], irows),
    ))

    # Table view — also the relief the palette's contrast warning requires.
    trows = []
    for t in turns[-120:]:
        m = t.get("mode") or {}
        trows.append([
            t["_when"].strftime("%Y-%m-%d %H:%M"),
            t.get("user_name") or "—",
            (t.get("user") or "")[:70],
            m.get("name") or "—",
            m.get("effort") or "—",
            (t.get("classifier") or {}).get("verdict")
            or ("explicit" if t.get("kind") == "librarian_explicit" else "—"),
            str(len(t.get("context_chunks") or [])),
            str(words((t.get("geddes") or {}).get("text", ""))),
            money((t.get("cost_cents") or {}).get("turn_total", 0.0) or 0.0),
        ])
    out.append(panel(
        "Every turn",
        "Most recent 120. The JSONL remains the source of truth; "
        "<code>python transcript.py &lt;date&gt;</code> renders a day in full.",
        table(["When", "Student", "Question", "Mode", "Effort", "Verdict",
               "Chunks", "Reply words", "Cost"], trows, cls="wide"),
    ))

    return "".join(out)


# --- page ------------------------------------------------------------------

CSS = """
:root{color-scheme:light;
--surface-0:#f4f4f2;--surface-1:#fcfcfb;--text-primary:#0b0b0b;
--text-secondary:#52514e;--muted:#898781;--axis:#c3c2b7;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
color-scheme:dark;--surface-0:#111110;--surface-1:#1a1a19;
--text-primary:#ffffff;--text-secondary:#c3c2b7;--muted:#898781;
--axis:#383835;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;}}
:root[data-theme="dark"]{color-scheme:dark;--surface-0:#111110;
--surface-1:#1a1a19;--text-primary:#ffffff;--text-secondary:#c3c2b7;
--muted:#898781;--axis:#383835;--series-1:#3987e5;--series-2:#d95926;
--series-3:#199e70;}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif;padding:0 16px 64px}
.wrap{max-width:860px;margin:0 auto}
header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
padding:32px 0 8px}
h1{font-size:1.5rem;margin:0;font-weight:650;letter-spacing:-.01em}
.sub{color:var(--text-secondary);font-size:.9rem}
button{margin-left:auto;background:var(--surface-1);color:var(--text-primary);
border:1px solid var(--axis);border-radius:8px;padding:6px 12px;
font:inherit;font-size:.85rem;cursor:pointer}
section{background:var(--surface-1);border:1px solid var(--axis);
border-radius:12px;padding:20px;margin:16px 0}
h2{font-size:1.05rem;margin:0 0 4px;font-weight:600}
.note{color:var(--text-secondary);font-size:.85rem;margin:0 0 16px;
max-width:64ch}
.warn{background:color-mix(in srgb,var(--series-2) 12%,transparent);
border-left:3px solid var(--series-2);padding:10px 14px;border-radius:6px;
font-size:.85rem;margin:14px 0 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px}
.tile{padding:2px 0}
.tval{font-size:1.7rem;font-weight:650;letter-spacing:-.02em;
font-variant-numeric:tabular-nums}
.tlab{font-size:.85rem;font-weight:550}
.tsub,.hcap .tsub{color:var(--muted);font-size:.78rem}
.hero{display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.hnum{font-size:3rem;font-weight:680;letter-spacing:-.03em;
font-variant-numeric:tabular-nums;line-height:1}
.hcap{font-size:.9rem;color:var(--text-secondary);max-width:44ch}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 12px;
font-size:.8rem;color:var(--text-secondary)}
.key{display:inline-flex;align-items:center;gap:6px}
.key i{width:10px;height:10px;border-radius:3px;display:inline-block}
.hbars{display:flex;flex-direction:column;gap:7px;margin:4px 0 16px}
.hrow{display:grid;grid-template-columns:minmax(90px,30%) 1fr auto;
gap:10px;align-items:center;font-size:.83rem}
.hlabel{color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
.htrack{background:color-mix(in srgb,var(--axis) 34%,transparent);
border-radius:4px;height:14px;overflow:hidden}
.hbar{height:100%;border-radius:4px;min-width:2px}
.hval{font-variant-numeric:tabular-nums;font-weight:550;min-width:3ch;
text-align:right}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--axis);stroke-width:1;opacity:.4}
.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:10px}
.dlabel{fill:var(--text-secondary);font-size:10px;font-weight:600}
.tablewrap{overflow-x:auto;margin-top:12px}
table{border-collapse:collapse;width:100%;font-size:.8rem}
th{text-align:left;font-weight:600;color:var(--text-secondary);
border-bottom:1px solid var(--axis);padding:7px 10px 7px 0;white-space:nowrap}
td{padding:6px 10px 6px 0;border-bottom:1px solid
color-mix(in srgb,var(--axis) 40%,transparent);vertical-align:top}
table.wide{min-width:760px}
.empty{color:var(--muted);font-size:.85rem;font-style:italic}
#tip{position:fixed;pointer-events:none;background:var(--text-primary);
color:var(--surface-1);padding:5px 9px;border-radius:6px;font-size:.78rem;
opacity:0;transition:opacity .1s;z-index:9;max-width:280px}
footer{color:var(--muted);font-size:.78rem;text-align:center;padding:28px 0}
@media (max-width:560px){.hrow{grid-template-columns:minmax(70px,38%) 1fr auto}
.hnum{font-size:2.2rem}}
"""

JS = """
var tip=document.getElementById('tip');
function show(e){var t=e.target.closest('[data-tip]');if(!t){return}
tip.textContent=t.getAttribute('data-tip');tip.style.opacity='1';move(e)}
function move(e){var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
if(x+r.width>innerWidth-8){x=e.clientX-r.width-14}
if(y+r.height>innerHeight-8){y=e.clientY-r.height-14}
tip.style.left=x+'px';tip.style.top=y+'px'}
function hide(e){if(e.target.closest('[data-tip]')){tip.style.opacity='0'}}
document.addEventListener('mouseover',show);
document.addEventListener('mousemove',function(e){
if(tip.style.opacity==='1'){move(e)}});
document.addEventListener('mouseout',hide);
var btn=document.getElementById('theme');
btn.addEventListener('click',function(){
var dark=matchMedia('(prefers-color-scheme:dark)').matches;
var cur=document.documentElement.getAttribute('data-theme')||(dark?'dark':'light');
document.documentElement.setAttribute('data-theme',cur==='dark'?'light':'dark')});
"""


def render(a: dict, generated: str, scope: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>geddes-folk — conversation log</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>geddes-folk</h1>
  <span class="sub">{esc(scope)} · generated {esc(generated)}</span>
  <button id="theme" type="button">Light / dark</button>
</header>
{build_panels(a)}
<footer>Read from logs/*.jsonl, which remains the source of truth.<br>
Regenerate with <code>python dashboard.py</code>.</footer>
</div>
<div id="tip"></div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=None,
                    help="only include the last N days")
    ap.add_argument("--out", default=None,
                    help="output path (default logs/dashboard.html)")
    args = ap.parse_args()

    turns = load(args.days)
    if not turns:
        print("No log records found in logs/*.jsonl — have a conversation first.")
        return 1

    out = Path(args.out) if args.out else LOGS / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    scope = f"last {args.days} days" if args.days else "all logs"
    out.write_text(
        render(analyse(turns),
               datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               scope),
        encoding="utf-8",
    )
    print(f"wrote {out}  ({len(turns)} turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
