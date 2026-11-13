/* evsoc box firmware core.
 *
 * Speaks the part of the ELM327 command set that evsoc profiles and common OBD apps use,
 * plus the EVS* commands from docs/box-protocol.md. Only read-only diagnostic services
 * leave the box (see box_request_allowed), independent of the program on the host.
 *
 * Output format follows the ELM327: lines end with CR (CR LF with ATL1), every answer
 * ends with an empty line and the prompt '>'. With ATH1 a CAN frame is printed as
 * <id><data>, 3 hex digits for 11-bit and 8 for 29-bit ids.
 */
#include "box.h"
#include "hal.h"

#include <stdio.h>
#include <string.h>

#define LINE_MAX 128
#define MAX_IDS 16
#define PENDING_WAIT_MS 5000u
#define SCAN_LISTEN_MS 200u

static struct {
    int echo, linefeed, spaces, headers, dlc;
    int caf, cfc;
    int protocol;               /* 0 auto, 6..9, 0xB user protocol (ATPB) */
    int auto_proto;             /* protocol found by the automatic search */
    uint8_t pb_options, pb_divisor;
    char header[9];             /* "" = default */
    uint8_t priority;           /* ATCP */
    char cra[9];                /* receive filter with X wildcards, "" = automatic */
    uint32_t cf, cm;
    int cf_set, cm_set;
    int cea;                    /* extended address of the target ECU, -1 = off */
    int fcsm;
    char fcsh[9];
    uint8_t fcsd[5];
    int fcsd_len;
    uint32_t timeout_ms;
    /* physical bus (EVS commands) */
    uint32_t evs_bitrate, evs_data_bitrate;
    int evs_fd, listen, pin_a, pin_b;
    /* what the CAN controller currently runs with */
    uint32_t hw_bitrate, hw_data_bitrate;
    int hw_fd, hw_listen, hw_valid;
    /* input */
    char line[LINE_MAX];
    int line_len, overflow, swallow_next;
} s;

/* -- output ------------------------------------------------------------------------ */

static void out(const char *t) { hal_out(t, (unsigned)strlen(t)); }
static void eol(void) { out(s.linefeed ? "\r\n" : "\r"); }
static void outln(const char *t) { out(t); eol(); }
static void prompt(void) { eol(); out(">"); }

/* -- helpers ------------------------------------------------------------------------ */

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int is_hex(const char *t)
{
    if (!*t) return 0;
    for (; *t; t++)
        if (hexval(*t) < 0) return 0;
    return 1;
}

static uint32_t parse_hex(const char *t)
{
    uint32_t v = 0;
    for (; *t; t++) v = (v << 4) | (uint32_t)hexval(*t);
    return v;
}

/* "07300800" -> bytes; returns count or -1 */
static int parse_bytes(const char *t, uint8_t *buf, int max)
{
    int n = (int)strlen(t);
    if (n % 2 || n / 2 > max) return -1;
    for (int i = 0; i < n / 2; i++) {
        int hi = hexval(t[2 * i]), lo = hexval(t[2 * i + 1]);
        if (hi < 0 || lo < 0) return -1;
        buf[i] = (uint8_t)(hi << 4 | lo);
    }
    return n / 2;
}

static int starts(const char *t, const char *prefix) { return strncmp(t, prefix, strlen(prefix)) == 0; }

/* -- read-only filter ---------------------------------------------------------------- */

int box_request_allowed(const uint8_t *req, size_t len)
{
    if (len == 0) return 0;
    switch (req[0]) {
    case 0x01: /* OBD current data */
    case 0x09: /* OBD vehicle information */
    case 0x22: /* UDS ReadDataByIdentifier */
    case 0x21: /* KWP ReadDataByLocalIdentifier */
    case 0x1A: /* KWP ReadEcuIdentification */
    case 0x3E: /* TesterPresent */
        return 1;
    case 0x10: /* session change, only default and extended */
        return len >= 2 && ((req[1] & 0x7F) == 0x01 || (req[1] & 0x7F) == 0x03);
    default:
        return 0;
    }
}

/* -- settings ------------------------------------------------------------------------ */

static void defaults(void)
{
    s.echo = 1;
    s.linefeed = 0;
    s.spaces = 1;
    s.headers = 0;
    s.dlc = 0;
    s.caf = 1;
    s.cfc = 1;
    s.protocol = 0;
    s.auto_proto = 0;
    s.pb_options = 0xE1;
    s.pb_divisor = 0x01;
    s.header[0] = 0;
    s.priority = 0x18;
    s.cra[0] = 0;
    s.cf_set = s.cm_set = 0;
    s.cea = -1;
    s.fcsm = 0;
    s.fcsh[0] = 0;
    s.fcsd_len = 0;
    s.timeout_ms = 0x32 * 4;
    s.evs_bitrate = 0;
    s.evs_data_bitrate = 0;
    s.evs_fd = 0;
    s.listen = 0;
    s.pin_a = 6;
    s.pin_b = 14;
    hal_select_pins(6, 14);
    s.hw_valid = 0;
}

void box_init(void)
{
    memset(&s, 0, sizeof s);
    defaults();
}

static int active_protocol(void) { return s.protocol ? s.protocol : (s.auto_proto ? s.auto_proto : 6); }

static int is_29bit(int proto)
{
    if (proto == 7 || proto == 9) return 1;
    if (proto == 0xB) return !(s.pb_options & 0x80);
    return 0;
}

static uint32_t bitrate_of(int proto)
{
    if (s.evs_bitrate) return s.evs_bitrate;
    if (proto == 8 || proto == 9) return 250000;
    if (proto == 0xB) return 500000u / (s.pb_divisor ? s.pb_divisor : 1);
    return 500000;
}

static int ensure_can(int proto)
{
    uint32_t br = bitrate_of(proto);
    if (s.hw_valid && s.hw_bitrate == br && s.hw_fd == s.evs_fd && s.hw_listen == s.listen &&
        s.hw_data_bitrate == s.evs_data_bitrate)
        return 0;
    if (hal_can_config(br, s.evs_data_bitrate, s.evs_fd, s.listen) != 0) return -1;
    s.hw_bitrate = br;
    s.hw_data_bitrate = s.evs_data_bitrate;
    s.hw_fd = s.evs_fd;
    s.hw_listen = s.listen;
    s.hw_valid = 1;
    return 0;
}

static uint32_t tx_id(int proto)
{
    size_t n = strlen(s.header);
    if (!is_29bit(proto)) return n ? (parse_hex(s.header) & 0x7FF) : 0x7DF;
    if (n == 8) return parse_hex(s.header);
    if (n == 6) return ((uint32_t)s.priority << 24) | parse_hex(s.header);
    return 0x18DB33F1;
}

static uint32_t id_from_text(const char *t, int *ext)
{
    size_t n = strlen(t);
    *ext = n > 3;
    if (n == 6) return ((uint32_t)s.priority << 24) | parse_hex(t);
    return parse_hex(t);
}

/* -- frames --------------------------------------------------------------------------- */

static int matches_cra(const box_frame *f)
{
    char id[9];
    size_t n = strlen(s.cra);
    if (f->ext) snprintf(id, sizeof id, "%08lX", (unsigned long)f->id);
    else snprintf(id, sizeof id, "%03lX", (unsigned long)f->id);
    if (strlen(id) != n) return 0;
    for (size_t i = 0; i < n; i++)
        if (s.cra[i] != 'X' && s.cra[i] != id[i]) return 0;
    return 1;
}

static int accept(const box_frame *f, uint32_t sent_id, int proto)
{
    if (s.cra[0]) return matches_cra(f);
    if (s.cf_set || s.cm_set) {
        uint32_t m = s.cm_set ? s.cm : 0xFFFFFFFFu;
        return (f->id & m) == (s.cf & m);
    }
    if (!is_29bit(proto)) {
        if (f->ext) return 0;
        return (f->id >= 0x7E8 && f->id <= 0x7EF) || f->id == sent_id + 8;
    }
    /* 29-bit normal fixed addressing: answers go to the tester, 18DA<tester><ecu> */
    return f->ext && ((f->id >> 16) & 0xFF) == 0xDA && ((f->id >> 8) & 0xFF) == (sent_id & 0xFF);
}

static void print_frame(const box_frame *f)
{
    char buf[3 * 64 + 16];
    int pos = 0, n = f->len, off = s.cea >= 0 ? 1 : 0;
    if (s.caf && !f->fd && n > off) {   /* single frame: drop the padding like the ELM327 */
        uint8_t pci = f->data[off];
        if ((pci >> 4) == 0 && (pci & 0x0F) && off + 1 + (pci & 0x0F) < n) n = off + 1 + (pci & 0x0F);
    }
    if (s.headers) {
        pos += snprintf(buf + pos, sizeof buf - pos, f->ext ? "%08lX" : "%03lX", (unsigned long)f->id);
        if (s.spaces) buf[pos++] = ' ';
    }
    if (s.dlc) {
        pos += snprintf(buf + pos, sizeof buf - pos, "%X", f->len > 15 ? 15 : f->len);
        if (s.spaces) buf[pos++] = ' ';
    }
    for (int i = 0; i < n; i++) {
        pos += snprintf(buf + pos, sizeof buf - pos, "%02X", f->data[i]);
        if (s.spaces && i + 1 < n) buf[pos++] = ' ';
    }
    buf[pos] = 0;
    outln(buf);
}

static void send_flow_control(const box_frame *rx, uint32_t sent_id, int proto)
{
    box_frame fc;
    memset(&fc, 0, sizeof fc);
    if (s.fcsm == 1 && s.fcsh[0]) {
        int ext;
        fc.id = id_from_text(s.fcsh, &ext);
        fc.ext = (uint8_t)ext;
        memcpy(fc.data, s.fcsd, (size_t)s.fcsd_len);
        fc.len = (uint8_t)s.fcsd_len;
    } else {
        int i = 0;
        fc.ext = (uint8_t)is_29bit(proto);
        if (fc.ext) /* swap source and target: 18DAF1DA -> 18DADAF1 */
            fc.id = (rx->id & 0xFFFF0000u) | ((rx->id & 0xFF) << 8) | ((rx->id >> 8) & 0xFF);
        else
            fc.id = sent_id == 0x7DF ? rx->id - 8 : sent_id;
        if (s.cea >= 0) fc.data[i++] = (uint8_t)s.cea;
        fc.data[i++] = 0x30; /* clear to send, no block limit, no gap */
        fc.data[i++] = 0x00;
        fc.data[i++] = 0x00;
        fc.len = (uint8_t)i;
    }
    if (!(s.pb_options & 0x40) || proto != 0xB)
        while (fc.len < 8) fc.data[fc.len++] = 0x00;
    hal_can_send(&fc);
}

/* Send one request on one protocol; prints the answers. Returns the number of frames. */
static int transact(const box_frame *req, int proto)
{
    box_frame rx;
    uint32_t deadline;
    int got = 0, off = s.cea >= 0 ? 1 : 0;
    if (ensure_can(proto) != 0) return -1;
    while (hal_can_recv(&rx)) {} /* drop old traffic */
    if (hal_can_send(req) != 0) return -1;
    deadline = hal_millis() + s.timeout_ms;
    while ((int32_t)(deadline - hal_millis()) > 0) {
        if (!hal_can_recv(&rx) || !accept(&rx, req->id, proto)) continue;
        print_frame(&rx);
        got++;
        deadline = hal_millis() + s.timeout_ms;
        if (rx.len > off + 3 && (rx.data[off] >> 4) == 0 && rx.data[off + 1] == 0x7F && rx.data[off + 3] == 0x78)
            deadline = hal_millis() + PENDING_WAIT_MS; /* response pending, real answer follows */
        else if (s.caf && s.cfc && rx.len > off && (rx.data[off] >> 4) == 1)
            send_flow_control(&rx, req->id, proto);
    }
    return got;
}

static void do_request(const char *hex)
{
    uint8_t raw[64], req[64];
    char tmp[2 * 64 + 2];
    int n, reqlen, off = s.cea >= 0 ? 1 : 0;
    size_t len = strlen(hex);
    if (s.listen) { outln("ERR LISTEN-ONLY"); return; }
    if (len > 2 * 64 + 1) { outln("?"); return; }
    memcpy(tmp, hex, len + 1);
    if (len % 2) tmp[len - 1] = 0; /* trailing "number of responses" digit */
    n = parse_bytes(tmp, raw, 64);
    if (n <= 0) { outln("?"); return; }
    if (s.caf) {
        memcpy(req, raw, (size_t)n);
        reqlen = n;
    } else { /* the host sends the ISO-TP PCI itself; only single frames are allowed */
        reqlen = raw[0] & 0x0F;
        if ((raw[0] >> 4) != 0 || reqlen == 0 || reqlen > n - 1) { outln("ERR BLOCKED"); return; }
        memcpy(req, raw + 1, (size_t)reqlen);
    }
    if (!box_request_allowed(req, (size_t)reqlen)) { outln("ERR BLOCKED"); return; }

    box_frame f;
    memset(&f, 0, sizeof f);
    if (off) f.data[f.len++] = (uint8_t)s.cea;
    if (s.caf) {
        if (reqlen > 7 - off) { outln("ERR TOO LONG"); return; } /* multi-frame requests: not needed for reading */
        f.data[f.len++] = (uint8_t)reqlen;
    }
    memcpy(f.data + f.len, s.caf ? req : raw, (size_t)(s.caf ? reqlen : n));
    f.len = (uint8_t)(f.len + (s.caf ? reqlen : n));
    if (f.len > 8) { outln("ERR TOO LONG"); return; }

    int protos[2] = {active_protocol(), 0};
    if (s.protocol == 0 && !s.auto_proto) protos[1] = 7; /* automatic: 11 bit first, then 29 bit */
    for (int i = 0; i < 2 && protos[i]; i++) {
        box_frame t = f;
        t.ext = (uint8_t)is_29bit(protos[i]);
        t.id = tx_id(protos[i]);
        if (!((s.pb_options & 0x40) && protos[i] == 0xB))
            while (t.len < 8) t.data[t.len++] = 0x00;
        int got = transact(&t, protos[i]);
        if (got < 0) { outln("CAN ERROR"); return; }
        if (got > 0) {
            if (s.protocol == 0) s.auto_proto = protos[i];
            return;
        }
    }
    outln("NO DATA");
}

static void monitor(void)
{
    box_frame rx;
    int proto = active_protocol();
    if (ensure_can(proto) != 0) { outln("CAN ERROR"); return; }
    while (!hal_input_pending()) {
        if (hal_can_recv(&rx) && (!s.cra[0] || matches_cra(&rx))) print_frame(&rx);
    }
    s.swallow_next = 1; /* the byte that stopped monitoring is not a command */
    outln("STOPPED");
}

/* -- EVS commands ----------------------------------------------------------------------- */

static const int PIN_PAIRS[][2] = {{6, 14}, {3, 11}, {12, 13}, {1, 9}};

static void evs_info(void)
{
    char buf[96] = "EVSOC-BOX " BOX_VERSION " KINDS=CAN,CANFD PINS=";
    int first = 1;
    for (unsigned i = 0; i < sizeof PIN_PAIRS / sizeof PIN_PAIRS[0]; i++) {
        if (hal_select_pins(PIN_PAIRS[i][0], PIN_PAIRS[i][1]) != 0) continue;
        size_t l = strlen(buf);
        snprintf(buf + l, sizeof buf - l, "%s%d/%d", first ? "" : ",", PIN_PAIRS[i][0], PIN_PAIRS[i][1]);
        first = 0;
    }
    hal_select_pins(s.pin_a, s.pin_b);
    strncat(buf, " LISTEN=1", sizeof buf - strlen(buf) - 1);
    outln(buf);
}

static void evs_bus(const char *args)
{
    char kind[8] = "";
    int a = 0, b = 0;
    unsigned long br = 0, dbr = 0;
    int n = sscanf(args, "%7s %d,%d %lu %lu", kind, &a, &b, &br, &dbr);
    int fd = strcmp(kind, "CANFD") == 0;
    if (n < 3) { outln("ERR SYNTAX"); return; }
    if (strcmp(kind, "CAN") != 0 && !fd) { outln("ERR KIND"); return; }
    if (hal_select_pins(a, b) != 0) { hal_select_pins(s.pin_a, s.pin_b); outln("ERR PINS"); return; }
    s.pin_a = a;
    s.pin_b = b;
    s.evs_bitrate = n >= 4 ? (uint32_t)br : 0;
    s.evs_fd = fd;
    s.evs_data_bitrate = fd ? (n >= 5 ? (uint32_t)dbr : 2000000u) : 0;
    s.hw_valid = 0;
    outln("OK");
}

static void evs_scan(void)
{
    static const uint32_t rates[] = {500000, 250000, 125000, 1000000};
    char line[160];
    box_frame rx;
    for (unsigned p = 0; p < sizeof PIN_PAIRS / sizeof PIN_PAIRS[0]; p++) {
        if (hal_select_pins(PIN_PAIRS[p][0], PIN_PAIRS[p][1]) != 0) continue;
        for (unsigned r = 0; r < sizeof rates / sizeof rates[0]; r++) {
            uint32_t ids[MAX_IDS];
            int nids = 0, frames = 0;
            if (hal_can_config(rates[r], 0, 0, 1) != 0) continue;
            uint32_t end = hal_millis() + SCAN_LISTEN_MS;
            while ((int32_t)(end - hal_millis()) > 0) {
                if (!hal_can_recv(&rx)) continue;
                frames++;
                int known = 0;
                for (int i = 0; i < nids; i++) known |= ids[i] == rx.id;
                if (!known && nids < MAX_IDS) ids[nids++] = rx.id;
            }
            if (!frames) continue;
            int pos = snprintf(line, sizeof line, "BUS CAN %d,%d %lu FRAMES=%d IDS=", PIN_PAIRS[p][0],
                               PIN_PAIRS[p][1], (unsigned long)rates[r], frames);
            for (int i = 0; i < nids && pos < (int)sizeof line - 10; i++)
                pos += snprintf(line + pos, sizeof line - pos, i ? ",%lX" : "%lX", (unsigned long)ids[i]);
            outln(line);
            break; /* first bitrate with traffic wins */
        }
    }
    s.pin_a = 6; /* back to the standard bus */
    s.pin_b = 14;
    s.evs_bitrate = s.evs_data_bitrate = 0;
    s.evs_fd = s.listen = 0;
    hal_select_pins(6, 14);
    s.hw_valid = 0;
    outln("OK");
}

/* -- AT commands ---------------------------------------------------------------------- */

static int flag(const char *arg, int *target)
{
    if ((arg[0] == '0' || arg[0] == '1') && !arg[1]) { *target = arg[0] == '1'; return 1; }
    return 0;
}

static void at_command(const char *c)
{
    const char *a;
    if (!strcmp(c, "Z") || !strcmp(c, "WS")) {
        defaults();
        eol();
        outln("ELM327 v2.1 (evsoc-box " BOX_VERSION ")");
        return;
    }
    if (!strcmp(c, "D")) { defaults(); outln("OK"); return; }
    if (!strcmp(c, "I")) { outln("ELM327 v2.1 (evsoc-box " BOX_VERSION ")"); return; }
    if (!strcmp(c, "@1")) { outln("evsoc-box universal adapter"); return; }
    if (!strcmp(c, "RV")) {
        int mv = hal_voltage_mv();
        char buf[16];
        if (mv < 0) { outln("?"); return; }
        snprintf(buf, sizeof buf, "%d.%dV", mv / 1000, (mv % 1000) / 100);
        outln(buf);
        return;
    }
    if (!strcmp(c, "DPN")) {
        char buf[4];
        snprintf(buf, sizeof buf, "%s%X", s.protocol == 0 ? "A" : "", active_protocol());
        outln(buf);
        return;
    }
    if (!strcmp(c, "DP")) {
        outln(is_29bit(active_protocol()) ? "ISO 15765-4 (CAN 29 bit)" : "ISO 15765-4 (CAN 11 bit)");
        return;
    }
    if (!strcmp(c, "MA")) { monitor(); return; }
    if (starts(c, "E") && flag(c + 1, &s.echo)) goto ok;
    if (starts(c, "L") && flag(c + 1, &s.linefeed)) goto ok;
    if (starts(c, "S") && flag(c + 1, &s.spaces)) goto ok;
    if (starts(c, "H") && flag(c + 1, &s.headers)) goto ok;
    if (starts(c, "D") && flag(c + 1, &s.dlc)) goto ok;
    if (starts(c, "CAF") && flag(c + 3, &s.caf)) goto ok;
    if (starts(c, "CFC") && flag(c + 3, &s.cfc)) goto ok;
    if (starts(c, "SP") || starts(c, "TP")) {
        a = c + 2;
        if (*a == 'A') a++;
        if (strlen(a) == 1 && (strchr("06789", *a) || *a == 'B')) {
            s.protocol = *a == 'B' ? 0xB : *a - '0';
            s.auto_proto = 0;
            goto ok;
        }
        goto unknown;
    }
    if (starts(c, "PB")) {
        uint8_t b[2];
        if (parse_bytes(c + 2, b, 2) != 2) goto unknown;
        s.pb_options = b[0];
        s.pb_divisor = b[1];
        goto ok;
    }
    if (starts(c, "SH")) {
        size_t n = strlen(c + 2);
        if ((n != 3 && n != 6 && n != 8) || !is_hex(c + 2)) goto unknown;
        strcpy(s.header, c + 2);
        goto ok;
    }
    if (starts(c, "CP")) {
        uint8_t b;
        if (parse_bytes(c + 2, &b, 1) != 1) goto unknown;
        s.priority = b;
        goto ok;
    }
    if (starts(c, "CRA") || starts(c, "SR")) {
        a = c + (c[0] == 'C' ? 3 : 2);
        size_t n = strlen(a);
        if (n && n != 3 && n != 8) goto unknown;
        for (size_t i = 0; i < n; i++)
            if (a[i] != 'X' && hexval(a[i]) < 0) goto unknown;
        strcpy(s.cra, a);
        goto ok;
    }
    if (starts(c, "CF") && is_hex(c + 2)) { s.cf = parse_hex(c + 2); s.cf_set = 1; s.cra[0] = 0; goto ok; }
    if (starts(c, "CM") && is_hex(c + 2)) { s.cm = parse_hex(c + 2); s.cm_set = 1; s.cra[0] = 0; goto ok; }
    if (starts(c, "CEA")) {
        uint8_t b;
        if (!c[3]) { s.cea = -1; goto ok; }
        if (parse_bytes(c + 3, &b, 1) != 1) goto unknown;
        s.cea = b;
        goto ok;
    }
    if (starts(c, "FCSH")) {
        size_t n = strlen(c + 4);
        if ((n != 3 && n != 6 && n != 8) || !is_hex(c + 4)) goto unknown;
        strcpy(s.fcsh, c + 4);
        goto ok;
    }
    if (starts(c, "FCSD")) {
        int n = parse_bytes(c + 4, s.fcsd, 5);
        if (n <= 0) goto unknown;
        s.fcsd_len = n;
        goto ok;
    }
    if (starts(c, "FCSM")) {
        if (!strcmp(c + 4, "0") || !strcmp(c + 4, "1")) { s.fcsm = c[4] - '0'; goto ok; }
        goto unknown;
    }
    if (starts(c, "ST")) {
        uint8_t b;
        if (parse_bytes(c + 2, &b, 1) != 1) goto unknown;
        s.timeout_ms = b ? (uint32_t)b * 4u : 0x32 * 4u;
        goto ok;
    }
    /* accepted without effect: adaptive timing, long messages, silent monitoring, init */
    if (starts(c, "AT") || starts(c, "AL") || starts(c, "NL") || starts(c, "CSM") || starts(c, "BI") ||
        starts(c, "TA") || starts(c, "IB") || starts(c, "CER") || starts(c, "KW") || starts(c, "SW"))
        goto ok;
unknown:
    outln("?");
    return;
ok:
    outln("OK");
}

/* -- input ---------------------------------------------------------------------------- */

static void execute(char *cmd)
{
    char compact[LINE_MAX];
    int n = 0;
    while (*cmd == ' ') cmd++;
    for (char *p = cmd; *p; p++)
        if (*p >= 'a' && *p <= 'z') *p = (char)(*p - 'a' + 'A');
    if (s.echo) outln(cmd);
    if (starts(cmd, "EVS")) {
        if (!strcmp(cmd, "EVSI")) evs_info();
        else if (starts(cmd, "EVSBUS ")) evs_bus(cmd + 7);
        else if (!strcmp(cmd, "EVSLISTEN 1") || !strcmp(cmd, "EVSLISTEN 0")) {
            s.listen = cmd[10] == '1';
            s.hw_valid = 0;
            outln("OK");
        } else if (!strcmp(cmd, "EVSSCAN")) evs_scan();
        else outln("?");
        prompt();
        return;
    }
    for (char *p = cmd; *p; p++)
        if (*p != ' ') compact[n++] = *p;
    compact[n] = 0;
    if (!n) { prompt(); return; } /* unlike the ELM327 a bare CR never repeats a request */
    if (starts(compact, "AT")) at_command(compact + 2);
    else if (is_hex(compact)) do_request(compact);
    else outln("?");
    prompt();
}

void box_input(char c)
{
    if (s.swallow_next) { s.swallow_next = 0; return; }
    if (c == '\n' || c == 0) return;
    if (c != '\r') {
        if (s.line_len < LINE_MAX - 1) s.line[s.line_len++] = c;
        else s.overflow = 1;
        return;
    }
    s.line[s.line_len] = 0;
    if (s.overflow) { outln("?"); prompt(); }
    else execute(s.line);
    s.line_len = 0;
    s.overflow = 0;
}
