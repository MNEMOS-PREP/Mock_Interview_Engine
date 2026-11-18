"""The question bank, drawn: `q_bank_discovered.pdf`.

The design (2026-11-18), from how revision material that works is laid out —
the sources and what each decided are in `qbank/README.md`:

* **By subject, with a contents page.** One divider page per subject — its
  own colour, what it covers, its topics — then its questions grouped by
  topic. The contents rows and the topics on a divider are links, the PDF's
  sidebar has a bookmark for every subject and topic, and a coloured tab on
  the page edge finds a subject with the thumb, as in a printed handbook.
* **The question first, the answer under it.** The question is a cue: read
  it, say yours out loud, then read the answer — recall before the check is
  what makes revising stick, and rereading answers alone does not.
* **What to cover, as a checklist** — the item's key points, to hold the
  spoken answer against — and **the follow-ups the interviewers asked**, each
  with its own answer: they are what comes next in the room.
* **Lines a reader can follow.** Body text runs about 70 characters a line
  (the 45–75 the print guides agree on), set in Inter; headings in Lora, the
  platform's own serif. Every answer says where it came from.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    Indenter,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from .book import Book, Entry, Subject

FILE_NAME = "q_bank_discovered.pdf"
FONTS_DIR = Path(__file__).with_name("fonts")

# The platform's colours (Platform_Shell theme.css, light).
INK = "#192d28"
SOFT = "#3a4a43"
FAINT = "#68766e"
LINE = "#dde5dc"
SUNKEN = "#f1f3ec"
BRAND = "#176b55"
NIGHT = "#0f3329"
MINT = "#9be8a8"
MIST = "#d3e8de"

W, H = A4
LEFT, RIGHT, TOP, BOTTOM = 58, 74, 78, 64
#: The question number sits in this gutter; everything else is indented by it.
GUTTER = 40
BODY_W = W - LEFT - RIGHT

_FONTS = {
    "QB-Inter": "Inter-Regular.ttf",
    "QB-Inter-Medium": "Inter-Medium.ttf",
    "QB-Inter-SemiBold": "Inter-SemiBold.ttf",
    "QB-Inter-Bold": "Inter-Bold.ttf",
    "QB-Inter-Italic": "Inter-Italic.ttf",
    "QB-Lora-SemiBold": "Lora-SemiBold.ttf",
    "QB-Lora-Bold": "Lora-Bold.ttf",
    "QB-Lora-Italic": "Lora-Italic.ttf",
    "QB-Fallback": "DejaVuSans.ttf",
}
_font_lock = threading.Lock()
_fonts_ready = False

#: What each answer is, in the words the page uses, and its mark's colour.
ANSWER_WORDS = {
    "reviewed": ("Reviewed answer", BRAND),
    "practice": ("Practice answer · not yet reviewed by a person", "#9a6b12"),
    "written": ("Answer written for your bank", "#40505e"),
    "guide": ("How to answer · put in your own facts", "#40505e"),
    "pending": ("Answer on its way", FAINT),
}


def fonts() -> None:
    global _fonts_ready
    with _font_lock:
        if _fonts_ready:
            return
        for name, file in _FONTS.items():
            pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / file)))
        pdfmetrics.registerFontFamily(
            "QB-Inter",
            normal="QB-Inter",
            bold="QB-Inter-SemiBold",
            italic="QB-Inter-Italic",
            boldItalic="QB-Inter-SemiBold",
        )
        _fonts_ready = True


def _cmap(font: str) -> dict[int, int]:
    return pdfmetrics.getFont(font).face.charToGlyph


def markup(text: str, font: str = "QB-Inter") -> str:
    """Text as paragraph markup: escaped, and any character the font lacks
    set in the fallback font (∈, ∪, ☐ are not in Inter) — or left out when
    neither has it, rather than printed as a box."""
    have, spare = _cmap(font), _cmap("QB-Fallback")
    out: list[str] = []
    for ch in " ".join(str(text).split()):
        code = ord(ch)
        if ch == " " or code in have:
            out.append(escape(ch))
        elif code in spare:
            out.append(f'<font name="QB-Fallback">{escape(ch)}</font>')
    return "".join(out)


def display_font(text: str, serif: str, sans: str = "QB-Inter-SemiBold") -> str:
    """Lora where it has every character (a heading), else Inter."""
    have = _cmap(serif)
    return serif if all(ord(c) in have for c in text if not c.isspace()) else sans


def tracked(canv, x: float, y: float, text: str, font: str, size: float, color, space: float = 1.1):
    t = canv.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(space)
    t.setFillColor(color)
    t.textOut(text)
    # PDF text state outlives the text object: without this, every line drawn
    # after a label on the page is letter-spaced too.
    t.setCharSpace(0)
    canv.drawText(t)


def tracked_width(text: str, font: str, size: float, space: float = 1.1) -> float:
    return pdfmetrics.stringWidth(text, font, size) + space * len(text)


def fit(text: str, font: str, size: float, width: float) -> str:
    """`text`, cut with an ellipsis to fit `width`."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _style(name: str, **kw) -> ParagraphStyle:
    base = {"fontName": "QB-Inter", "fontSize": 10, "leading": 14, "textColor": HexColor(INK)}
    base.update(kw)
    return ParagraphStyle(name, **base)


STYLES = {
    "question": _style("q", fontName="QB-Inter-SemiBold", fontSize=11.5, leading=16.2),
    "meta": _style("meta", fontSize=7.8, leading=11, textColor=HexColor(FAINT)),
    "answer": _style("a", fontSize=10.4, leading=15.6, textColor=HexColor(INK)),
    "point": _style(
        "p",
        fontSize=9.4,
        leading=13.6,
        textColor=HexColor(SOFT),
        leftIndent=15,
        bulletIndent=0,
        bulletFontName="QB-Fallback",
        bulletFontSize=9.4,
        spaceAfter=2.5,
    ),
    "fu_q": _style(
        "fq",
        fontName="QB-Inter-SemiBold",
        fontSize=9.9,
        leading=14,
        leftIndent=14,
        firstLineIndent=-14,
        spaceBefore=6,
    ),
    "fu_a": _style(
        "fa", fontSize=9.6, leading=14.2, textColor=HexColor(SOFT), leftIndent=14, spaceBefore=2
    ),
    "note": _style(
        "n",
        fontName="QB-Inter-Italic",
        fontSize=8.6,
        leading=12,
        textColor=HexColor(FAINT),
        leftIndent=14,
        spaceBefore=5,
    ),
    "cover_sub": _style("cs", fontSize=12, leading=18.5, textColor=HexColor(MIST)),
    "step": _style("st", fontSize=9.6, leading=14, textColor=HexColor(SOFT)),
    "title_white": _style("tw", fontName="QB-Lora-Bold", fontSize=34, leading=39, textColor=white),
    "blurb_white": _style("bw", fontSize=11.5, leading=17, textColor=HexColor("#eef7f2")),
    "empty": _style("e", fontSize=11, leading=17, textColor=HexColor(SOFT)),
}


# ── what one drawing knows ───────────────────────────────────────────────────


@dataclass
class _State:
    book: Book
    updated: datetime
    #: Page numbers from the first pass: subject index → page, for contents.
    known: dict[str, int] = field(default_factory=dict)
    #: Page numbers this pass records.
    pages: dict[str, int] = field(default_factory=dict)
    subject: Subject | None = None
    index: int = 0

    @property
    def stamp(self) -> str:
        return self.updated.strftime("%d %b %Y, %H:%M").lstrip("0")


class _Mark(Flowable):
    """Nothing on the page; something done at its place in the story."""

    def __init__(self, act: Callable[[object], None]):
        super().__init__()
        self.act = act
        self.width = self.height = 0

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self.act(self.canv)


class _Anchor(Flowable):
    """A page whose art is its template's: this holds its place, names it as
    a destination, and records where it fell."""

    def __init__(self, state: _State, key: str, outline: str | None = None, level: int = 0):
        super().__init__()
        self.state, self.key, self.outline, self.level = state, key, outline, level
        self.width = self.height = 1

    def wrap(self, aw, ah):
        return 1, 1

    def draw(self):
        canv = self.canv
        canv.bookmarkPage(self.key)
        if self.outline:
            canv.addOutlineEntry(self.outline, self.key, level=self.level, closed=self.level == 0)
        self.state.pages[self.key] = canv.getPageNumber()


class _Label(Flowable):
    """A small tracked capital label: "SAY IT LIKE THIS"."""

    def __init__(self, text: str, color: str, after: float = 5):
        super().__init__()
        self.text, self.color, self.after = text.upper(), color, after

    def wrap(self, aw, ah):
        return aw, 7.4 + self.after

    def draw(self):
        tracked(
            self.canv, 0, self.after, self.text, "QB-Inter-SemiBold", 7.1, HexColor(self.color), 0.9
        )


class _QuestionHead(Flowable):
    """The question, with its number in the gutter."""

    def __init__(self, number: int, text: str, accent: str):
        super().__init__()
        self.number, self.accent = number, accent
        self.para = Paragraph(markup(text, "QB-Inter-SemiBold"), STYLES["question"])

    def wrap(self, aw, ah):
        _, self.para_h = self.para.wrap(aw - GUTTER, ah)
        self.width, self.height = aw, max(self.para_h, 17)
        return self.width, self.height

    def draw(self):
        canv = self.canv
        label = f"Q{self.number}"
        size = 8.2
        pill_w = max(27.0, pdfmetrics.stringWidth(label, "QB-Inter-Bold", size) + 12)
        top = self.height
        canv.setFillColor(HexColor(self.accent))
        canv.roundRect(0, top - 16.5, pill_w, 16, 8, stroke=0, fill=1)
        canv.setFillColor(white)
        canv.setFont("QB-Inter-Bold", size)
        canv.drawCentredString(pill_w / 2, top - 11.8, label)
        self.para.drawOn(canv, GUTTER, top - self.para_h)


class _TopicHeading(Flowable):
    def __init__(self, state: _State, key: str, name: str, count: int, accent: str):
        super().__init__()
        self.state, self.key, self.name, self.count, self.accent = state, key, name, count, accent

    def wrap(self, aw, ah):
        self.width = aw
        return aw, 36

    def draw(self):
        canv = self.canv
        canv.bookmarkPage(self.key)
        canv.addOutlineEntry(self.name, self.key, level=1)
        self.state.pages[self.key] = canv.getPageNumber()
        right = f"{self.count} question{'' if self.count == 1 else 's'}"
        canv.setFont("QB-Inter", 8.2)
        canv.setFillColor(HexColor(FAINT))
        canv.drawRightString(self.width, 15, right)
        room = self.width - pdfmetrics.stringWidth(right, "QB-Inter", 8.2) - 16
        font = display_font(self.name, "QB-Lora-SemiBold")
        canv.setFont(font, 15)
        canv.setFillColor(HexColor(INK))
        canv.drawString(0, 14, fit(self.name, font, 15, room))
        canv.setFillColor(HexColor(self.accent))
        canv.rect(0, 4, 30, 2.2, stroke=0, fill=1)
        canv.setStrokeColor(HexColor(LINE))
        canv.setLineWidth(0.6)
        canv.line(34, 5.1, self.width, 5.1)


# ── the pages' art ───────────────────────────────────────────────────────────


def _footer(canv, state: _State) -> None:
    canv.setFont("QB-Inter", 7.4)
    canv.setFillColor(HexColor(FAINT))
    canv.drawString(LEFT, 34, f"Updated {state.stamp}  ·  {FILE_NAME}")
    canv.setFont("QB-Inter-SemiBold", 8)
    canv.setFillColor(HexColor(INK))
    canv.drawRightString(W - RIGHT + 16, 34, str(canv.getPageNumber()))


def _tab(canv, state: _State) -> None:
    """The thumb tab: one per subject, lower down the edge for each."""
    subject = state.subject
    if subject is None:
        return
    count = max(1, len(state.book.subjects))
    span = min(54.0, (H - 200) / count)
    y = H - 118 - state.index * span
    canv.setFillColor(HexColor(subject.accent))
    canv.roundRect(W - 13, y - span + 6, 30, span - 6, 4, stroke=0, fill=1)
    canv.setFillColor(white)
    canv.setFont("QB-Inter-Bold", 6.6)
    canv.drawCentredString(W - 6.5, y - span / 2, f"{state.index + 1:02d}")


def _cover(canv, doc, state: _State) -> None:
    book = state.book
    band = 438
    canv.saveState()
    canv.setFillColor(HexColor(NIGHT))
    canv.rect(0, H - band, W, band, stroke=0, fill=1)
    # Rings, quietly: the one ornament.
    canv.setStrokeColor(Color(0.61, 0.91, 0.66, alpha=0.10))
    canv.setLineWidth(1)
    for r in range(70, 360, 42):
        canv.circle(W - 40, H - 96, r, stroke=1, fill=0)
    tracked(
        canv,
        LEFT,
        H - 82,
        "AI INTERVIEWER  ·  YOUR QUESTION BANK",
        "QB-Inter-SemiBold",
        8.2,
        HexColor(MINT),
        1.8,
    )
    canv.setFillColor(white)
    canv.setFont("QB-Lora-Bold", 48)
    canv.drawString(LEFT - 2, H - 168, "Question Bank")
    canv.setFillColor(HexColor(MINT))
    canv.setFont("QB-Lora-Italic", 27)
    canv.drawString(LEFT, H - 206, "discovered in your interviews")
    sub = Paragraph(
        "Every question you have met in a mock interview, grouped by subject, with an answer "
        "written to be said out loud — and the follow-ups the interviewers asked next.",
        STYLES["cover_sub"],
    )
    _, h = sub.wrap(W - LEFT - 150, 200)
    sub.drawOn(canv, LEFT, H - 238 - h)
    who = f"Prepared for {book.name}   ·   " if book.name else ""
    canv.setFont("QB-Inter-Medium", 9.6)
    canv.setFillColor(HexColor(MINT))
    canv.drawString(LEFT, H - band + 40, f"{who}Updated {state.stamp}")

    # Three counts.
    top = H - band - 30
    gap, tile_h = 14, 76
    tile_w = (W - 2 * LEFT - 2 * gap) / 3
    counts = [
        (book.questions, "question" if book.questions == 1 else "questions"),
        (book.follow_ups, "follow-up" if book.follow_ups == 1 else "follow-ups"),
        (len(book.subjects), "subject" if len(book.subjects) == 1 else "subjects"),
    ]
    for n, (value, word) in enumerate(counts):
        x = LEFT + n * (tile_w + gap)
        canv.setFillColor(HexColor(SUNKEN))
        canv.roundRect(x, top - tile_h, tile_w, tile_h, 10, stroke=0, fill=1)
        canv.setFillColor(HexColor(INK))
        canv.setFont("QB-Lora-Bold", 30)
        canv.drawString(x + 16, top - 44, str(value))
        canv.setFillColor(HexColor(FAINT))
        canv.setFont("QB-Inter", 9)
        canv.drawString(x + 17, top - 62, word)

    # How to use it.
    y = top - tile_h - 40
    canv.setFillColor(HexColor(INK))
    canv.setFont("QB-Lora-SemiBold", 15)
    canv.drawString(LEFT, y, "How to revise with this")
    steps = [
        (
            "Read the question, then cover the answer.",
            "Say yours out loud first. Recalling an answer before you check it is what "
            "makes it stick; rereading answers does far less.",
        ),
        (
            "Check yours against “Make sure you cover”.",
            "Each point you left out is the one to say again tomorrow.",
        ),
        (
            "Practise the follow-ups.",
            "They are what the interviewers asked next — and what they will ask next time.",
        ),
    ]
    y -= 24
    for n, (head, rest) in enumerate(steps, start=1):
        canv.setFillColor(HexColor(BRAND))
        canv.circle(LEFT + 9, y - 5, 9, stroke=0, fill=1)
        canv.setFillColor(white)
        canv.setFont("QB-Inter-Bold", 8.5)
        canv.drawCentredString(LEFT + 9, y - 8, str(n))
        para = Paragraph(f"<b>{escape(head)}</b> {escape(rest)}", STYLES["step"])
        _, h = para.wrap(W - LEFT - LEFT - 30, 100)
        para.drawOn(canv, LEFT + 28, y - h + 5)
        y -= h + 14

    canv.setFont("QB-Inter", 7.8)
    canv.setFillColor(HexColor(FAINT))
    canv.drawString(
        LEFT, 46, "This file rebuilds itself after every question you answer in an interview."
    )
    canv.drawString(LEFT, 34, "Download it again from Today for the newest version.")
    canv.setFont("QB-Inter-SemiBold", 7.8)
    canv.drawRightString(W - LEFT, 34, FILE_NAME)
    canv.restoreState()


def _contents(canv, doc, state: _State) -> None:
    book = state.book
    canv.saveState()
    canv.setFillColor(HexColor(INK))
    canv.setFont("QB-Lora-Bold", 28)
    canv.drawString(LEFT, H - 104, "Contents")
    tracked(
        canv,
        LEFT,
        H - 124,
        f"{len(book.subjects)} SUBJECTS · {book.questions} QUESTIONS",
        "QB-Inter-SemiBold",
        7.4,
        HexColor(FAINT),
        1.2,
    )
    y = H - 168
    if not book.subjects:
        para = Paragraph(
            "Nothing here yet. Your bank fills in as you answer questions in a mock interview: "
            "each one you answer is added here with an answer to revise from.",
            STYLES["empty"],
        )
        _, h = para.wrap(W - 2 * LEFT, 200)
        para.drawOn(canv, LEFT, y - h)
        canv.restoreState()
        _footer(canv, state)
        return
    row = 46 if len(book.subjects) <= 12 else max(26, (y - 150) / len(book.subjects))
    for n, subject in enumerate(book.subjects):
        key = f"s{n}"
        top = y - n * row
        canv.setFillColor(HexColor(subject.accent))
        canv.roundRect(LEFT, top - 22, 26, 22, 5, stroke=0, fill=1)
        canv.setFillColor(white)
        canv.setFont("QB-Inter-Bold", 8.4)
        canv.drawCentredString(LEFT + 13, top - 14.6, f"{n + 1:02d}")
        page = state.known.get(key)
        page_text = str(page) if page else ""
        canv.setFont("QB-Inter-SemiBold", 10.5)
        canv.setFillColor(HexColor(INK))
        right = W - LEFT
        canv.drawRightString(right, top - 14, page_text)
        title_font = "QB-Inter-SemiBold"
        title = fit(subject.title, title_font, 12, right - LEFT - 110)
        canv.setFont(title_font, 12)
        canv.drawString(LEFT + 38, top - 10, title)
        entries = subject.entries
        follow = sum(len(e.follow_ups) for e in entries)
        detail = (
            f"{len(subject.topics)} topic{'' if len(subject.topics) == 1 else 's'}  ·  "
            f"{len(entries)} question{'' if len(entries) == 1 else 's'}  ·  "
            f"{follow} follow-up{'' if follow == 1 else 's'}"
        )
        if row >= 40:
            canv.setFont("QB-Inter", 8.4)
            canv.setFillColor(HexColor(FAINT))
            canv.drawString(LEFT + 38, top - 24, detail)
        # Dotted leader from the title to the page number.
        start = LEFT + 46 + pdfmetrics.stringWidth(title, title_font, 12)
        canv.setStrokeColor(HexColor(LINE))
        canv.setDash(1, 3)
        canv.line(start, top - 12, right - 22, top - 12)
        canv.setDash()
        canv.linkAbsolute("", key, (LEFT, top - row + 8, right, top + 2))

    # What the marks on an answer mean.
    y = BOTTOM + 70
    canv.setFont("QB-Inter-SemiBold", 8)
    canv.setFillColor(HexColor(INK))
    canv.drawString(LEFT, y + 14, "Where each answer comes from")
    for n, kind in enumerate(("reviewed", "practice", "written")):
        words, color = ANSWER_WORDS[kind]
        canv.setFillColor(HexColor(color))
        canv.circle(LEFT + 4, y - 4 - n * 14, 3, stroke=0, fill=1)
        canv.setFillColor(HexColor(SOFT))
        canv.setFont("QB-Inter", 8)
        canv.drawString(LEFT + 14, y - 7 - n * 14, words)
    canv.restoreState()
    _footer(canv, state)


def _divider(canv, doc, state: _State) -> None:
    subject = state.subject
    if subject is None:
        return
    n = state.index
    band = 318
    canv.saveState()
    canv.setFillColor(HexColor(subject.accent))
    canv.rect(0, H - band, W, band, stroke=0, fill=1)
    canv.setFillColor(Color(1, 1, 1, alpha=0.13))
    canv.setFont("QB-Lora-Bold", 200)
    canv.drawRightString(W - 30, H - band + 26, f"{n + 1:02d}")
    tracked(
        canv,
        LEFT,
        H - 86,
        f"SUBJECT {n + 1:02d} OF {len(state.book.subjects):02d}",
        "QB-Inter-SemiBold",
        8,
        Color(1, 1, 1, alpha=0.82),
        1.8,
    )
    title_style = ParagraphStyle(
        "dt",
        parent=STYLES["title_white"],
        fontName=display_font(subject.title, "QB-Lora-Bold", "QB-Inter-Bold"),
    )
    title = Paragraph(markup(subject.title, title_style.fontName), title_style)
    _, th = title.wrap(W - LEFT - 170, 200)
    title.drawOn(canv, LEFT, H - 112 - th)
    if subject.blurb:
        blurb = Paragraph(markup(subject.blurb), STYLES["blurb_white"])
        _, bh = blurb.wrap(W - LEFT - 190, 120)
        blurb.drawOn(canv, LEFT, H - 128 - th - bh)

    entries = subject.entries
    follow = sum(len(e.follow_ups) for e in entries)
    y = H - band - 44
    canv.setFillColor(HexColor(subject.accent))
    canv.setFont("QB-Inter-SemiBold", 12)
    canv.drawString(
        LEFT,
        y,
        f"{len(entries)} question{'' if len(entries) == 1 else 's'}   ·   "
        f"{follow} follow-up{'' if follow == 1 else 's'}   ·   "
        f"{len(subject.topics)} topic{'' if len(subject.topics) == 1 else 's'}",
    )
    y -= 36
    tracked(canv, LEFT, y, "IN THIS SUBJECT", "QB-Inter-SemiBold", 7.4, HexColor(FAINT), 1.2)
    y -= 22
    col_w = (W - 2 * LEFT - 24) / 2
    per_col = max(1, (len(subject.topics) + 1) // 2)
    row = 23 if per_col <= 12 else max(15, (y - BOTTOM - 40) / per_col)
    for t, topic in enumerate(subject.topics):
        col, line = divmod(t, per_col)
        x = LEFT + col * (col_w + 24)
        ty = y - line * row
        count = str(len(topic.entries))
        canv.setFillColor(HexColor(subject.accent))
        canv.circle(x + 3, ty + 3, 2.6, stroke=0, fill=1)
        canv.setFont("QB-Inter", 7.8)
        canv.setFillColor(HexColor(FAINT))
        canv.drawRightString(x + col_w, ty, count)
        canv.setFont("QB-Inter", 10.2)
        canv.setFillColor(HexColor(INK))
        canv.drawString(x + 13, ty, fit(topic.name, "QB-Inter", 10.2, col_w - 36))
        canv.setStrokeColor(HexColor(LINE))
        canv.setLineWidth(0.5)
        canv.line(x + 13, ty - 7, x + col_w, ty - 7)
        canv.linkAbsolute("", f"s{n}t{t}", (x, ty - 8, x + col_w, ty + 12))
    canv.restoreState()
    _tab(canv, state)
    _footer(canv, state)


def _content(canv, doc, state: _State) -> None:
    subject = state.subject
    canv.saveState()
    if subject is not None:
        label = f"{state.index + 1:02d}   {subject.title.upper()}"
        tracked(
            canv,
            LEFT,
            H - 46,
            fit(label, "QB-Inter-SemiBold", 7.4, BODY_W - 120),
            "QB-Inter-SemiBold",
            7.4,
            HexColor(subject.accent),
            1.1,
        )
    right = "QUESTION BANK"
    tracked(
        canv,
        W - RIGHT + 16 - tracked_width(right, "QB-Inter-SemiBold", 7, 1.1),
        H - 46,
        right,
        "QB-Inter-SemiBold",
        7,
        HexColor(FAINT),
        1.1,
    )
    canv.setStrokeColor(HexColor(LINE))
    canv.setLineWidth(0.6)
    canv.line(LEFT, H - 56, W - RIGHT + 16, H - 56)
    canv.restoreState()
    _tab(canv, state)
    _footer(canv, state)


# ── one question ─────────────────────────────────────────────────────────────


def _meta(entry: Entry) -> Paragraph:
    words, color = ANSWER_WORDS.get(entry.answer_kind, ANSWER_WORDS["pending"])
    parts = []
    if entry.asked and entry.times:
        when = ""
        if entry.first_at:
            when = " · first " + datetime.fromisoformat(entry.first_at).strftime("%d %b %Y").lstrip(
                "0"
            )
        parts.append(f"Asked {'once' if entry.times == 1 else f'{entry.times} times'}{when}")
    parts.append(f'<font color="{color}" name="QB-Inter-SemiBold">● </font>{escape(words)}')
    return Paragraph("   ·   ".join(parts), STYLES["meta"])


def _answer_box(entry: Entry, subject: Subject, width: float) -> Table:
    if entry.answer:
        if entry.answer_kind == "guide":
            label = "How to answer"
        elif subject.personal:
            label = "An example answer · tell your own story"
        else:
            label = "Say it like this"
        inner = [_Label(label, subject.accent), Paragraph(markup(entry.answer), STYLES["answer"])]
    else:
        inner = [
            _Label("Say it like this", subject.accent),
            Paragraph(
                "This answer is still being written. Download the bank again in a little while.",
                STYLES["note"],
            ),
        ]
    table = Table([[inner]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor(subject.tint)),
                ("LINEBEFORE", (0, 0), (0, -1), 2.4, HexColor(subject.accent)),
                ("LEFTPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
            ]
        )
    )
    return table


def _entry(number: int, entry: Entry, subject: Subject, box: str) -> list[Flowable]:
    head = [
        _QuestionHead(number, entry.question, subject.accent),
        Spacer(1, 4),
        Indenter(left=GUTTER),
        _meta(entry),
        Spacer(1, 8),
        _answer_box(entry, subject, BODY_W - GUTTER),
        Indenter(left=-GUTTER),
    ]
    rest: list[Flowable] = [Indenter(left=GUTTER)]
    if entry.key_points:
        points = [_Label("Make sure you cover", FAINT, after=6)]
        points += [
            Paragraph(markup(point), STYLES["point"], bulletText=box) for point in entry.key_points
        ]
        rest += [Spacer(1, 10), KeepTogether(points)]
    if entry.follow_ups:
        rest += [Spacer(1, 10), _Label("They followed up with", FAINT, after=1)]
        for follow in entry.follow_ups:
            block = [
                Paragraph(f"↳  {markup(follow.question, 'QB-Inter-SemiBold')}", STYLES["fu_q"])
            ]
            if follow.answer:
                block.append(Paragraph(markup(follow.answer), STYLES["fu_a"]))
            rest.append(KeepTogether(block))
        if entry.follow_ups_pending:
            rest.append(
                Paragraph(
                    "Answers to these are being written. "
                    "Download the bank again in a little while.",
                    STYLES["note"],
                )
            )
    rest.append(Indenter(left=-GUTTER))
    return [CondPageBreak(150), KeepTogether(head), *rest]


# ── the book ─────────────────────────────────────────────────────────────────


def _story(state: _State) -> list[Flowable]:
    book = state.book
    box = "☐" if 0x2610 in _cmap("QB-Fallback") else "□"
    story: list[Flowable] = [
        _Anchor(state, "cover", "Cover"),
        NextPageTemplate("contents"),
        PageBreak(),
        _Anchor(state, "contents", "Contents"),
    ]
    number = 0
    for n, subject in enumerate(book.subjects):

        def enter(_canv, n=n, subject=subject):
            state.subject, state.index = subject, n

        story += [
            _Mark(enter),
            NextPageTemplate("divider"),
            PageBreak(),
            _Anchor(state, f"s{n}", f"{n + 1:02d}  {subject.title}"),
            NextPageTemplate("content"),
            PageBreak(),
        ]
        for t, topic in enumerate(subject.topics):
            story += [
                CondPageBreak(190),
                _TopicHeading(state, f"s{n}t{t}", topic.name, len(topic.entries), subject.accent),
                Spacer(1, 12),
            ]
            for e, entry in enumerate(topic.entries):
                number += 1
                story += _entry(number, entry, subject, box)
                if e < len(topic.entries) - 1:
                    story.append(
                        HRFlowable(
                            width="100%",
                            thickness=0.6,
                            color=HexColor(LINE),
                            spaceBefore=14,
                            spaceAfter=16,
                        )
                    )
            story.append(Spacer(1, 26))
    return story


def _draw(state: _State) -> bytes:
    buffer = io.BytesIO()
    book = state.book
    title = f"Question Bank — {book.name}" if book.name else "Question Bank"
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=LEFT,
        rightMargin=RIGHT,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title=title,
        author="AI Interviewer",
        subject="Every interview question met, with answers to revise from",
        creator="AI Interviewer · M06 Mock Interview Engine",
        pageCompression=1,
    )
    whole = Frame(
        0, 0, W, H, id="whole", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
    )
    body = Frame(
        LEFT,
        BOTTOM,
        BODY_W,
        H - TOP - BOTTOM,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )

    def paint(fn):
        return lambda canv, d: fn(canv, d, state)

    doc.addPageTemplates(
        [
            PageTemplate("cover", [whole], onPage=paint(_cover)),
            PageTemplate("contents", [whole], onPage=paint(_contents)),
            PageTemplate("divider", [whole], onPage=paint(_divider)),
            PageTemplate("content", [body], onPage=paint(_content)),
        ]
    )
    doc.build(_story(state))
    return buffer.getvalue()


def render(book: Book, *, updated: datetime) -> bytes:
    """The PDF. Drawn twice: the first pass finds the page each subject
    starts on, the second prints those pages in the contents."""
    fonts()
    first = _State(book=book, updated=updated)
    _draw(first)
    second = _State(book=book, updated=updated, known=dict(first.pages))
    return _draw(second)


__all__ = ["FILE_NAME", "markup", "render"]
