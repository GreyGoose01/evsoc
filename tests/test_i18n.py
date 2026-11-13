"""English and German: catalogue, translation rules, terminal and web pages."""

import re
import sys
import urllib.request

import pytest

from evsoc import i18n
from evsoc.cli import LABELS, main


def test_catalogue_is_consistent():
    pairs = i18n.load_pairs()
    keys = [en for en, _ in pairs]
    assert len(keys) == len(set(keys)), "duplicate entries"
    for en, de in pairs:
        gaps = en.count("{}")
        marks = re.findall(r"\{(\d*)\}", de)
        if gaps:
            assert marks, f"{en!r}: placeholders missing in the German text"
            numbered = [m for m in marks if m]
            assert len(marks) == gaps or numbered, f"{en!r}: {gaps} gaps, {len(marks)} placeholders"
            assert all(int(m) < gaps for m in numbered)
        else:
            assert not marks, f"{en!r}: placeholder without a gap"


def test_every_value_label_has_a_german_name():
    missing = [label for label in LABELS.values() if i18n.tr(label, "de") == label]
    assert missing == []


@pytest.mark.parametrize("en,de", [
    ("State of charge (SoC)", "Ladestand (SoC)"),
    ("   Testing 7 profiles completely ...", "   Teste 7 Profile vollständig ..."),
    # a message inside a message is translated as well
    ("Error: No connection to 10.0.0.1:35000: refused. Is the computer on the adapter's WiFi?",
     "Fehler: Keine Verbindung zu 10.0.0.1:35000: refused. Ist der Mac im WLAN des Adapters?"),
    ("active, confirmed", "aktiv, bestätigt"),                                     # list of known words
    ("soh   -   (Answer too short: 24 bits needed, 16 present)", "soh   -   (Antwort zu kurz: 24 Bits nötig, 16 vorhanden)"),
    ("2E0101: Service 0x2E with this parameter is not allowed.", "2E0101: Service 0x2E mit diesem Parameter ist nicht erlaubt."),
    ("12:01:10  Disconnected", "12:01:10  Verbindung getrennt"),                  # log line with the time
    ("3A5  Byte 3–4 (16 bit, big endian) × 0.01", "3A5  Byte 3–4 (16 Bit, höherwertiges zuerst) × 0.01"),
    ("evsoc_corsa_e", "evsoc_corsa_e"),                                           # unknown text stays as it is
])
def test_translation_rules(en, de):
    assert i18n.tr(en, "de") == de
    assert i18n.tr(en, "en") == en


def test_language_choice(monkeypatch):
    for var in ("EVSOC_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.detect() == "en"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detect() == "de"
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert i18n.detect() == "en"
    monkeypatch.setenv("EVSOC_LANG", "de")
    assert i18n.detect() == "de"
    with pytest.raises(ValueError):
        i18n.set_lang("fr")


def test_terminal_in_german(capsys):
    stdout = sys.stdout
    assert main(["--lang", "de", "read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--all"]) == 0
    out = capsys.readouterr().out
    assert "Ladestand (SoC)" in out and "Gesundheit (SoH)" in out and "State of charge" not in out
    assert sys.stdout is stdout and i18n.lang() == "en"                           # restored afterwards
    assert main(["--lang", "de", "read", "-a", "tcp://127.0.0.1:1", "-p", "evsoc_stellantis_ecmp"]) == 1
    assert "Fehler: Keine Verbindung zu 127.0.0.1:1" in capsys.readouterr().err
    assert main(["read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp"]) == 0
    assert "State of charge (SoC)" in capsys.readouterr().out                    # English stays English


def test_german_output_of_the_main_commands(capsys, tmp_path):
    """Every line the common commands print has a German version (nothing English left over)."""
    english = re.compile(r"\b(the|and|with|not|found|answer|answers|request|requests|profiles?|values?|vehicle|"
                         r"control units?|report|reading|testing|trying|attempt|state of charge)\b", re.I)
    runs = [["read", "-a", "mock://corsa-e"],
            ["probe", "-a", "mock://corsa-e", "--car", "Corsa-e", "--note", "soc=80", "-o", str(tmp_path / "p.json")],
            ["wake", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--duration", "0.01", "--interval", "0.2",
             "-o", str(tmp_path / "w.json")],
            ["plan", "Leaf ZE0", "-a", "mock://corsa-e", "--limit", "1"]]
    german = re.compile(r"[äöüßÄÖÜ]|\b(der|die|das|und|nicht|mit|Profile|Werte|Antworten|Anfragen|Fahrzeug|Bericht)\b")
    leftovers = []
    for args in runs:
        main(["--lang", "de", *args])
        captured = capsys.readouterr()
        for line in (captured.out + captured.err).splitlines():
            if english.search(line) and not german.search(line) and "evsoc_" not in line and tmp_path.name not in line:
                leftovers.append(line)
    assert leftovers == []


def test_help_in_german(capsys):
    with pytest.raises(SystemExit):
        main(["--lang", "de", "probe", "--help"])
    out = capsys.readouterr().out
    assert "abgelesener Wert zum Vergleich" in out and "value read off" not in out


def test_german_option_names_still_work(capsys):
    assert main(["--nur-kabel", "read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--json", "--akku-kwh", "50"]) == 0
    assert '"soc"' in capsys.readouterr().out


def test_web_pages_carry_the_catalogue():
    import threading

    from evsoc.cli import open_adapter
    from evsoc.gui import serve
    server = serve(open_adapter, port=0, open_browser=False, token="t")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/") as r:
            page = r.read().decode()
    finally:
        server.shutdown()
        for extra in server.extra:
            extra.shutdown()
        server.server_close()
    assert "window.EVSOC_I18N = [[" in page and '"Start test drive", "Probelauf starten"' in page
    assert "lang-switch" in page and page.index("EVSOC_I18N") < page.index("</head>")
