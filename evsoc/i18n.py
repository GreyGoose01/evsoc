"""English and German.

evsoc's texts are written in English. For German, every text that reaches a person passes through
`tr()`: in the terminal a wrapper around stdout/stderr translates each line, in the browser the same
catalogue translates the page (see web/i18n.js). The catalogue `lang/de.txt` holds one entry per line:

    Reading the vehicle identification number (VIN) ... || Lese Fahrgestellnummer (VIN) ...
    Testing {} profiles completely || Teste {} Profile vollständig

`{}` stands for any text (a number, a name, another message, which is translated in turn); `{0}`,
`{1}` in the German text change the order. A line is looked up whole first, then as a template; if
nothing matches, longer phrases inside it are replaced, and anything unknown stays English.

Language: `--lang en|de`, else `EVSOC_LANG`, else the system language (`LANG`, `LC_ALL`, ...),
English for anything that is not German.
"""

from __future__ import annotations

import io
import os
import re
from functools import lru_cache
from pathlib import Path

CATALOGUE = Path(__file__).parent / "lang" / "de.txt"
LANGS = ("en", "de")
_lang: str | None = None


def detect() -> str:
    for var in ("EVSOC_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var, "").strip().lower()
        if value and value not in ("c", "posix", "c.utf-8"):
            return "de" if value.startswith("de") else "en"
    return "en"


def lang() -> str:
    return _lang or detect()


def set_lang(value: str | None) -> None:
    global _lang
    if value is not None and value not in LANGS:
        raise ValueError(f"Unknown language {value!r}, possible: {', '.join(LANGS)}")
    _lang = value


# -- catalogue -------------------------------------------------------------------------------------

def load_pairs(path: Path = CATALOGUE) -> list[tuple[str, str]]:
    pairs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        de, sep, en = line.partition(" || ")
        if not sep or not de.strip() or not en.strip():
            raise ValueError(f"{path.name}:{n}: expected 'English || German'")
        pairs.append((de.strip(), en.strip()))
    return pairs


def _template(de: str) -> re.Pattern:
    parts = de.split("{}")
    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(parts) - 1:
            regex += "(.+)" if i == len(parts) - 2 and parts[-1] == "" else "(.+?)"
    return re.compile(regex, re.S)


@lru_cache(maxsize=1)
def catalogue() -> tuple[dict[str, str], list[tuple[re.Pattern, str]], list[tuple[re.Pattern, str]]]:
    """(exact texts, templates, phrases replaced inside longer lines)."""
    exact: dict[str, str] = {}
    templates: list[tuple[re.Pattern, str]] = []
    phrases: list[tuple[str, str]] = []
    for de, en in load_pairs():
        if "{}" in de:
            templates.append((_template(de), en))
        else:
            exact[de] = en
            if " " in de and len(de) >= 8:
                phrases.append((de, en))
    # more specific templates first: more literal text, then fewer gaps
    templates.sort(key=lambda t: (-len(re.sub(r"\(\.\+\??\)", "", t[0].pattern)), t[0].pattern))
    phrases.sort(key=lambda p: -len(p[0]))
    compiled = [(re.compile(r"(?<![\wäöüÄÖÜß])" + re.escape(de) + r"(?![\wäöüÄÖÜß])"), en) for de, en in phrases]
    return exact, templates, compiled


def _fill(en: str, groups: tuple[str, ...], depth: int) -> str:
    counter = iter(range(len(groups)))

    def one(m: re.Match) -> str:
        i = int(m.group(1)) if m.group(1) else next(counter)
        return _translate(groups[i], depth + 1) if i < len(groups) else m.group(0)
    return re.sub(r"\{(\d*)\}", one, en)


def _translate(text: str, depth: int = 0) -> str:
    core = text.strip()
    if not core or depth > 4:
        return text
    lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    exact, templates, phrases = catalogue()
    if core in exact:
        return lead + exact[core] + trail
    for pattern, en in templates:
        m = pattern.fullmatch(core)
        if m:
            return lead + _fill(en, m.groups(), depth) + trail
    out = core
    for pattern, en in phrases:
        if pattern.search(out):
            out = pattern.sub(lambda _m, en=en: en, out)
    if out == core:
        out = _fallback(core, depth)
    return lead + out + trail


def _trailing_group(text: str) -> int | None:
    """Index of the '(' that opens a bracket group closing at the very end of text."""
    if not text.endswith(")"):
        return None
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(text[i], 0)
        if depth == 0:
            return i
    return None


def _fallback(core: str, depth: int) -> str:
    """Lines put together from pieces: 'a, b' lists, a message in trailing brackets, 'name: message'."""
    exact = catalogue()[0]
    stamp = re.match(r"(\(?\d\d:\d\d:\d\d[.\d]*\)?\s+)(.+)", core, re.S)
    if stamp:  # log lines start with the time
        return stamp.group(1) + _translate(stamp.group(2), depth + 1)
    if ", " in core and all(part in exact for part in core.split(", ")):
        return ", ".join(exact[part] for part in core.split(", "))
    start = _trailing_group(core)
    if start is not None and start > 0:
        inner = core[start + 1:-1]
        done = _translate(inner, depth + 1)
        if done != inner:
            return _translate(core[:start], depth + 1) + "(" + done + ")"
    head, sep, rest = core.partition(": ")
    if sep and head and " " not in head.strip():
        done = _translate(rest, depth + 1)
        if done != rest:
            return head + sep + done
    return core


def tr(text: str, to: str | None = None) -> str:
    """English text -> the current language (line by line)."""
    if (to or lang()) != "de" or not text:
        return text
    return "\n".join(_translate(line) for line in text.split("\n"))


def as_json() -> list[list[str]]:
    """The catalogue for the browser (web/i18n.js applies the same rules)."""
    return [[de, en] for de, en in load_pairs()]


# -- terminal ----------------------------------------------------------------------------------------

class TranslatingStream(io.TextIOBase):
    """Wraps stdout/stderr and translates every complete line."""

    def __init__(self, inner):
        self.inner = inner
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        if "\n" in self._buf:
            done, self._buf = self._buf.rsplit("\n", 1)
            self.inner.write(tr(done, "de") + "\n")
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self.inner.write(tr(self._buf, "de"))
            self._buf = ""
        self.inner.flush()

    def isatty(self) -> bool:
        return self.inner.isatty()

    def fileno(self) -> int:
        return self.inner.fileno()

    @property
    def encoding(self):  # noqa: D401 - mirrors the wrapped stream
        return getattr(self.inner, "encoding", "utf-8")

    def __getattr__(self, name):
        return getattr(self.inner, name)


def translate_parser(parser) -> None:
    """argparse help texts (which are wrapped before printing, so they are translated beforehand)."""
    import argparse
    parser.description = tr(parser.description) if parser.description else parser.description
    parser.epilog = tr(parser.epilog) if parser.epilog else parser.epilog
    for action in parser._actions:
        if action.help and action.help is not argparse.SUPPRESS:
            action.help = tr(action.help)
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                choice.help = tr(choice.help) if choice.help else choice.help
            for sub in dict.fromkeys(action.choices.values()):
                translate_parser(sub)


def page(html: str) -> str:
    """Inline the catalogue and the translator (web/i18n.js) into a web page."""
    import json
    script = (Path(__file__).parent / "web" / "i18n.js").read_text(encoding="utf-8")
    data = json.dumps(as_json(), ensure_ascii=False).replace("</", "<\\/")
    block = f"<script>window.EVSOC_I18N = {data};</script>\n<script>{script}</script>\n"
    return html.replace("</head>", block + "</head>", 1)
