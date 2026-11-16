import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from evsoc.cli import open_adapter
from evsoc.gui import serve


@pytest.fixture
def gui():
    server = serve(open_adapter, port=0, open_browser=False, token="test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield server, base
    server.session.stop_monitor()
    server.session.disconnect()
    server.shutdown()
    for extra in server.extra:
        extra.shutdown()
    server.server_close()


def call(base, path, body=None, token="test-token", headers=None):
    h = {"X-Evsoc-Token": token} if token else {}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_contains_token_and_api_needs_it(gui):
    _server, base = gui
    with urllib.request.urlopen(base + "/") as r:
        assert "test-token" in r.read().decode()
    assert call(base, "/api/info", token=None)[0] == 403
    assert call(base, "/api/info", token="falsch")[0] == 403
    status, info = call(base, "/api/info")
    assert status == 200 and info["profiles"] > 200


def test_foreign_host_header_is_rejected(gui):
    _server, base = gui
    assert call(base, "/api/info", headers={"Host": "evil.example:80"})[0] == 403


def test_post_requires_json(gui):
    _server, base = gui
    req = urllib.request.Request(base + "/api/connect", data=b"url=mock://corsa-e", method="POST",
                                 headers={"X-Evsoc-Token": "test-token", "Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 415


def test_connect_search_plan_read(gui):
    _server, base = gui
    status, conn = call(base, "/api/connect", {"url": "mock://corsa-e"})
    assert status == 200 and conn["caps"]["kinds"]
    _, rows = call(base, "/api/models?q=e-208")
    assert any(r["profile"] == "evsoc_stellantis_ecmp" for r in rows)
    _, plan = call(base, "/api/plan?profile=evsoc_stellantis_ecmp")
    assert plan[0]["buses"] == ["CAN, 500 kbit/s, 11 bit, pins 6/14"]
    assert plan[0]["adapter_check"]["problems"] == []
    status, reading = call(base, "/api/read", {"profile": "evsoc_stellantis_ecmp", "all": True})
    assert status == 200 and reading["soc"] == pytest.approx(79.96, abs=0.01)
    labels = {v["name"]: v["label"] for v in reading["values"]}
    assert labels["voltage"] == "Voltage"
    _, st = call(base, "/api/status")
    assert st["connected"] and st["history"]


def test_read_soh_with_nominal_capacity(gui):
    _server, base = gui
    call(base, "/api/connect", {"url": "mock://id4"})
    _, reading = call(base, "/api/read", {"profile": "evsoc_vw_meb", "all": True, "battery_kwh": "77"})
    soh = next(v for v in reading["values"] if v["name"] == "soh")
    assert soh["label"] == "Health (SoH)" and soh["value"] == pytest.approx(95.325)


def test_read_with_wrong_adapter_explains(gui):
    _server, base = gui
    call(base, "/api/connect", {"url": "mock://corsa-e"})
    status, err = call(base, "/api/read", {"profile": "evsoc_nissan_leaf_evcan"})
    assert status == 400 and "pins 12/13" in err["error"]


def test_autodetect_via_gui(gui):
    _server, base = gui
    call(base, "/api/connect", {"url": "box:mock://leaf"})
    status, reading = call(base, "/api/read", {"car": "Leaf"})
    assert status == 200 and reading["detection"] and reading["soc"] == pytest.approx(65.0)


def test_monitor_start_stop(gui):
    _server, base = gui
    assert call(base, "/api/monitor/start", {"url": "mock://corsa-e", "profile": "evsoc_stellantis_ecmp", "interval": 10})[0] == 200
    for _ in range(50):
        _, st = call(base, "/api/status")
        if st["monitor"]["state"] and st["monitor"]["state"].get("soc"):
            break
        time.sleep(0.1)
    assert st["monitor"]["running"] and st["monitor"]["state"]["status"] == "awake"
    assert st["monitor"]["state"]["labels"]["soc"] == "State of charge (SoC)"
    assert call(base, "/api/read", {})[0] == 400          # manual reading is blocked while monitoring
    assert call(base, "/api/monitor/stop", {})[0] == 200
    assert call(base, "/api/status")[1]["monitor"]["running"] is False


def test_lan_mode_needs_token_for_the_page():
    server = serve(open_adapter, host="0.0.0.0", port=0, open_browser=False, token="lan-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/")
        assert e.value.code == 403
        with urllib.request.urlopen(base + "/?token=lan-token") as r:
            assert r.status == 200
        assert "?token=lan-token" in server.url
    finally:
        server.shutdown()
        server.server_close()


# -- test drive, tools, desktop --------------------------------------------------------------------

@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("EVSOC_REPORTS", str(tmp_path / "reports"))
    return tmp_path / "reports"


def test_probe_runs_as_job_and_report_can_be_reopened(gui, reports):
    server, base = gui
    assert call(base, "/api/probe/start", {})[0] == 400  # no adapter yet
    call(base, "/api/connect", {"url": "mock://corsa-e"})
    assert call(base, "/api/probe/start", {"car": "Corsa-e", "notes": "soc=80, soh=70", "raw": "ATSH6B4 ATCRA694 22D810"})[0] == 200
    assert call(base, "/api/connect", {"url": "mock://corsa-e"})[0] == 400 or not server.session.job["running"]
    job = server.session.wait_job()
    assert job["error"] is None and not job["running"]
    assert any("evsoc_stellantis_ecmp" in line for line in call(base, "/api/job")[1]["lines"])

    view = call(base, "/api/probe")[1]["report"]
    assert view["autodetect"] == "evsoc_stellantis_ecmp" and view["notes"] == {"soc": 80.0, "soh": 70.0}
    ecmp = next(p for p in view["profiles"] if p["name"] == "evsoc_stellantis_ecmp")
    by_name = {v["name"]: v for v in ecmp["values"]}
    assert ecmp["chosen"] and by_name["soc"]["note"]["match"] is True and by_name["soh"]["note"]["match"] is False
    assert by_name["soc"]["label"] == "State of charge (SoC)"
    assert view["units"][0]["dtcs"][1]["code"] == "U0111-87" and len(view["raw"]) == 1
    assert "requests" not in view or isinstance(view["requests"], int)  # raw answers stay out of the page view

    full = call(base, "/api/probe/report")[1]
    saved = call(base, "/api/reports")[1]
    assert saved["folder"] == str(reports) and [r["name"] for r in saved["reports"]] == [full["file"].split("/")[-1]]
    again = call(base, "/api/probe/load", {"name": saved["reports"][0]["name"], "notes": ["soc=20"]})[1]["report"]
    assert again["notes"]["soc"] == 20.0
    uploaded = call(base, "/api/probe/load", {"report": full})[1]["report"]
    assert uploaded["autodetect"] == "evsoc_stellantis_ecmp" and uploaded["file"] is None
    assert call(base, "/api/probe/load", {"name": "../../etc/passwd"})[0] == 400
    assert call(base, "/api/probe/load", {"report": {"nix": 1}})[0] == 400


def test_raw_commands_and_read_only_guard(gui):
    _server, base = gui
    call(base, "/api/connect", {"url": "mock://corsa-e"})
    status, r = call(base, "/api/raw", {"commands": "ATSH6B4 ATCRA694 22D80F-22D810 2E010001 14FFFFFF"})
    assert status == 200
    results = {x["cmd"]: x for x in r["results"]}
    assert results["22D810"]["payload"] == "62 D8 10 9F EB" and results["ATSH6B4"]["ok"]
    assert "error" in results["22D80F"]
    assert "not allowed" in results["2E010001"]["error"] and "not allowed" in results["14FFFFFF"]["error"]
    hits = call(base, "/api/raw", {"commands": "ATSH6B4 ATCRA694 22D80F-22D810", "hits_only": True})[1]["results"]
    assert [x["cmd"] for x in hits] == ["22D810"]
    assert call(base, "/api/raw", {"commands": "22D8-22D810"})[0] == 400


def test_bus_scan_needs_the_box(gui):
    _server, base = gui
    call(base, "/api/connect", {"url": "mock://corsa-e"})
    assert call(base, "/api/busscan", {})[0] == 400
    call(base, "/api/connect", {"url": "box:mock://leaf"})
    buses = call(base, "/api/busscan", {})[1]["buses"]
    assert {b["pins"] for b in buses} == {"6/14", "12/13", "3/11"}


def test_capture_file_is_analysed(gui):
    _server, base = gui
    log = ("(1.000) can0 6B4#0322D81000000000\n(1.010) can0 694#0562D8109FEB0000\n"
           "(2.000) can0 6B4#0322D81000000000\n(2.010) can0 694#0562D8109FEB0000\n")
    status, r = call(base, "/api/sniff/analyze", {"text": log, "values": ["soc 79.96"]})
    assert status == 200 and "22D810" in r["text"].replace(" ", "") and "evsoc_stellantis_ecmp" in r["text"]
    assert call(base, "/api/sniff/analyze", {"text": "not a capture"})[0] == 400


def test_listening_in_runs_as_job(gui, reports):
    server, base = gui
    assert call(base, "/api/sniff/mark", {"text": "soc 80"})[0] == 400  # nothing running
    assert call(base, "/api/sniff/start", {"url": "mock://corsa-e", "seconds": 1})[0] == 200
    job = server.session.wait_job()
    assert job["error"] is None, job["error"]
    assert "Capture saved" in job["result"]["text"]
    assert list(reports.glob("capture-*.log"))


def test_desktop_entry_and_app_window(tmp_path, monkeypatch):
    from evsoc import gui as g
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry, icon = g.install_desktop("/opt/evsoc/.venv/bin/evsoc")
    text = entry.read_text()
    assert "Exec=/opt/evsoc/.venv/bin/evsoc gui --window" in text and "Terminal=false" in text and f"Icon={icon}" in text
    assert icon.read_text().startswith("<svg")
    assert set(g.remove_desktop()) == {entry, icon} and g.remove_desktop() == []

    started = []
    monkeypatch.setattr(g.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    monkeypatch.setattr(g.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    assert g.open_window("http://127.0.0.1:1/") == "chromium" and started[0][1] == "--app=http://127.0.0.1:1/"
    monkeypatch.setattr(g.shutil, "which", lambda name: None)
    monkeypatch.setattr(g.webbrowser, "open", lambda url: started.append(url))
    assert g.open_window("http://127.0.0.1:1/") == "default browser" and started[-1] == "http://127.0.0.1:1/"


def test_default_browser_does_not_write_into_the_terminal(monkeypatch):
    import evsoc.gui as g
    started = []
    monkeypatch.setattr(g.sys, "platform", "linux")
    monkeypatch.setattr(g.shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    monkeypatch.setattr(g.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
    g.open_url("http://127.0.0.1:1/")
    cmd, kw = started[0]
    assert cmd == ["/usr/bin/xdg-open", "http://127.0.0.1:1/"]
    assert kw["stdout"] is g.subprocess.DEVNULL and kw["stderr"] is g.subprocess.DEVNULL and kw["start_new_session"]


def test_window_mode_stops_when_the_page_is_gone(gui):
    from evsoc.gui import idle_seconds
    server, base = gui
    call(base, "/api/status")
    assert idle_seconds(server) < 5
    server.session.last_request -= 500
    assert idle_seconds(server) > 400
    server.session.job["running"] = True  # never while work is in progress
    assert idle_seconds(server) == 0
    server.session.job["running"] = False


def test_wake_test_and_reading_on_demand(gui, reports):
    server, base = gui
    assert call(base, "/api/monitor/wake", {})[0] == 400  # continuous operation is off
    assert call(base, "/api/waketest/start", {"url": "mock://corsa-e", "profile": "evsoc_stellantis_ecmp",
                                              "minutes": 0.01, "step": 0.1})[0] == 200
    job = server.session.wait_job()
    assert job["error"] is None and job["result"]["woke"] and "Wake test" in job["result"]["text"]
    assert list(reports.glob("evsoc-waketest-*.json"))

    call(base, "/api/monitor/start", {"url": "mock://corsa-e", "profile": "evsoc_stellantis_ecmp", "interval": 600})
    for _ in range(50):
        if call(base, "/api/status")[1]["monitor"]["state"]:
            break
        time.sleep(0.1)
    first = call(base, "/api/status")[1]["monitor"]["state"]["checked"]
    time.sleep(1.1)
    assert call(base, "/api/monitor/wake", {})[0] == 200   # ends the 10-minute pause at once
    for _ in range(50):
        if call(base, "/api/status")[1]["monitor"]["state"]["checked"] != first:
            break
        time.sleep(0.1)
    assert call(base, "/api/status")[1]["monitor"]["state"]["checked"] != first


def test_closing_the_page_quits_after_a_short_grace(gui):
    from evsoc.gui import page_gone
    server, base = gui
    call(base, "/api/status")
    assert not page_gone(server)
    assert call(base, "/api/bye", {})[0] == 200
    assert not page_gone(server)                     # a reload asks again within the grace period
    server.session.page_closed -= 11
    assert page_gone(server)
    call(base, "/api/status")                        # page came back (reload)
    assert server.session.page_closed is None and not page_gone(server)
    server.session.last_request -= 200               # closed without goodbye: silent for 3 minutes
    assert page_gone(server)
    server.session.job["running"] = True             # never while work is in progress
    call(base, "/api/bye", {})
    server.session.page_closed -= 60
    assert not page_gone(server)
    server.session.job["running"] = False
