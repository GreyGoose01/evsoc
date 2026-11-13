import pytest

from evsoc.elm import ElmAdapter, NegativeResponse, NoResponse, isotp_reassemble
from evsoc.safety import SafetyError, check_request, decode_request


class Dummy:
    def write(self, data): ...
    def read(self, timeout): return b""
    def close(self): ...


def parse(req_hex, lines, ext=None, tester=None):
    elm = ElmAdapter(Dummy())
    elm.ext_addr, elm.tester_addr = ext, tester
    return elm.parse_response(bytes.fromhex(req_hex), lines)


def test_real_corsa_e_line():
    # Captured with Car Scanner on an Opel Corsa-e at 54.79 % displayed SoC.
    r = parse("22D410", ["6940562D4106D9D"])
    assert r.ecu == "694"
    assert r.payload == bytes.fromhex("62D4106D9D")
    assert int.from_bytes(r.payload[3:5], "big") / 512 == pytest.approx(54.8, abs=0.05)


def test_multiframe_with_spaces_and_29bit():
    lines = [
        "SEARCHING...",
        "18 DA F1 DB 10 0A 62 90 02 13 88 00",
        "18 DA F1 DB 21 11 22 33 44 55 AA AA",
    ]
    r = parse("229002", [l for l in lines])
    assert r.ecu == "18DAF1DB"
    assert r.payload == bytes.fromhex("6290021388001122 3344".replace(" ", ""))


def test_bmw_extended_addressing():
    lines = ["607F1100962DDBC024C", "607F12103A60069FFFF"]
    r = parse("22DDBC", lines, ext=0x07, tester=0xF1)
    assert r.payload == bytes.fromhex("62DDBC024C03A60069")


def test_picks_matching_ecu_among_several():
    lines = ["7E803415B10", "7E9037F2231", "7EA03620105"]
    assert parse("015B", lines).payload == bytes.fromhex("415B10")


def test_response_pending_then_answer():
    r = parse("220101", ["7EC037F2278", "7EC04620101AB"])
    assert r.payload == bytes.fromhex("620101AB")


def test_negative_response():
    with pytest.raises(NegativeResponse, match="requestOutOfRange"):
        parse("22F190", ["7E8037F2231"])


@pytest.mark.parametrize("lines", [["NO DATA"], ["CAN ERROR"], [], ["UNABLE TO CONNECT"]])
def test_no_data(lines):
    with pytest.raises(NoResponse):
        parse("22D410", lines)


def test_isotp_truncated_message_is_kept():
    assert isotp_reassemble([bytes.fromhex("1010620101AABBCC")]) == [bytes.fromhex("620101AABBCC")]


def test_caf0_decoding():
    assert decode_request("0322028C55555555", caf=False) == bytes.fromhex("22028C")
    assert decode_request("22 02 8C") == bytes.fromhex("22028C")


@pytest.mark.parametrize("req", ["2EF19001", "3101FF00", "1101", "14FFFFFF", "2701", "1002", "3D00"])
def test_safety_blocks_writes(req):
    with pytest.raises(SafetyError):
        check_request(bytes.fromhex(req))


@pytest.mark.parametrize("req", ["22DDBC", "015B", "0902", "2105", "1003", "3E00"])
def test_safety_allows_reads(req):
    check_request(bytes.fromhex(req))


def test_request_refuses_before_sending():
    sent = []

    class Spy(Dummy):
        def write(self, data):
            sent.append(data)

    with pytest.raises(SafetyError):
        ElmAdapter(Spy()).request("2EF19001")
    assert sent == []


from evsoc.elm import at_family  # noqa: E402
from evsoc.mock import MockElmTransport  # noqa: E402


def test_at_family():
    assert at_family("AT SH 7E4") == "SH"
    assert at_family("ATFCSD300000") == "FCSD"
    assert at_family("ATSPB") == "SP"
    assert at_family("ATAL") == at_family("ATNL") == "LEN"
    assert at_family("ATBI") is None


def test_unchanged_settings_are_not_resent():
    t = MockElmTransport("corsa-e")
    elm = ElmAdapter(t)
    elm.reset()
    t.sent.clear()
    elm.at("ATSH6B4")
    elm.at("ATSH6B4")
    elm.at("ATSH7E4")
    assert t.sent == ["ATSH6B4", "ATSH7E4"]


def test_prepare_resets_only_when_settings_would_leak():
    t = MockElmTransport("bmw-i3")
    elm = ElmAdapter(t)
    elm.reset()
    elm.at("ATSH6F1")
    elm.at("ATCEA07")
    assert elm.prepare(["ATSH6F1", "ATCEA07"]) is False
    assert elm.prepare(["ATSH7E4"]) is True  # CEA would leak into an 11-bit normal-addressing request
    assert elm.ext_addr is None


def test_trailing_response_count_digit_is_stripped():
    t = MockElmTransport("corsa-e")
    elm = ElmAdapter(t)
    elm.reset()
    elm.at("ATSH6B4")
    r = elm.request("22D4101")
    assert r.payload == bytes.fromhex("62D4109FEB")
    assert t.sent[-1] == "22D410"


def test_listen_tesla_frame():
    elm = ElmAdapter(MockElmTransport("tesla-m3"))
    elm.reset()
    frame = elm.listen("292")
    assert len(frame) == 8


def test_raw_bytes_kept_for_wican():
    r = parse("220105", ["7EC100962010500000000", "7EC210000009E00000000"])
    assert r.payload[:3] == bytes.fromhex("620105")
    assert r.raw[:2] == bytes.fromhex("1009")
