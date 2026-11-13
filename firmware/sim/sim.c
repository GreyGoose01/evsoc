/* Host simulator for the evsoc box firmware.
 *
 * Runs the unchanged firmware core (core/box.c) on a PC, behind a pseudo terminal, with
 * simulated control units on a virtual CAN bus. evsoc connects to it like to the real
 * box:  evsoc read -a box:/dev/pts/N
 *
 *   ./evsoc-box-sim [corsa-e|bmw-i3|id4|leaf]     prints the device path on stdout
 *
 * Multi-frame answers are only continued after a correct flow control frame from the
 * box, so the simulator also checks the firmware's ISO-TP handling.
 */
#define _XOPEN_SOURCE 600
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE  /* macOS: keep cfmakeraw() visible next to _XOPEN_SOURCE */
#include "../core/box.h"
#include "../core/hal.h"

#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    uint32_t req_id;
    int ext_id;          /* 29-bit request id */
    int target;          /* extended address of the ECU (BMW), -1 = none */
    const char *request; /* hex, e.g. "22D410" */
    uint32_t resp_id;
    const char *answer;  /* complete UDS answer in hex */
    uint32_t fc_id;      /* where the ECU expects flow control */
    int pins_a;          /* bus the ECU sits on */
} ecu_entry;

typedef struct {
    const char *name;
    const ecu_entry *ecus;
    uint32_t broadcast_id; /* periodic frame (passive listening), 0 = none */
    int broadcast_pin;
    const char *broadcast_data;
} car;

static const ecu_entry CORSA[] = {
    {0x6B4, 0, -1, "22D410", 0x694, "62D4109FEB", 0x6B4, 6},
    {0x6B4, 0, -1, "22D810", 0x694, "62D8109FEB", 0x6B4, 6},
    {0x6B4, 0, -1, "22D860", 0x694, "62D8600105DD", 0x6B4, 6},
    {0x7DF, 0, -1, "0902", 0x7E8, "490201565233554A5A4B5A4B4C3132333435", 0x7E0, 6},
    {0},
};
static const ecu_entry BMW_I3[] = {
    {0x6F1, 0, 0x07, "22DDBC", 0x607, "62DDBC024C03A60069", 0x6F1, 6},
    {0x6F1, 0, 0x07, "226335", 0x607, "62633500000054", 0x6F1, 6},
    {0},
};
static const ecu_entry ID4[] = {
    {0x17FC007B, 1, -1, "22028C", 0x17FE007B, "62028CB4", 0x17FC007B, 6},
    {0x17FC0076, 1, -1, "223DEF", 0x17FE0076, "623DEF1F40", 0x17FC0076, 6},
    {0x710, 0, -1, "222AB2", 0x77A, "622AB205BC0400", 0x710, 6},
    {0x710, 0, -1, "222AB8", 0x77A, "622AB80000058000000000", 0x710, 6},
    {0},
};
static const ecu_entry NONE[] = {{0}};

static const car CARS[] = {
    {"corsa-e", CORSA, 0, 0, NULL},
    {"bmw-i3", BMW_I3, 0, 0, NULL},
    {"id4", ID4, 0, 0, NULL},
    {"leaf", NONE, 0x55B, 12, "A200000000000000"}, /* EV-CAN on pins 12/13: SoC 64.8 % */
};

static const car *g_car;
static int g_master = -1;
static int g_pins_a = 6, g_listen;
static uint32_t g_bitrate;

/* -- virtual bus -------------------------------------------------------------------- */

#define QMAX 64
static box_frame q[QMAX];
static int qhead, qtail;
static uint8_t pending[256];  /* rest of a multi-frame answer, waiting for flow control */
static int pending_len, pending_seq, pending_target;
static uint32_t pending_resp, pending_fc;
static int pending_ext;
static uint32_t last_broadcast;

static void push(uint32_t id, int ext, const uint8_t *d, int n)
{
    box_frame *f = &q[qtail];
    memset(f, 0, sizeof *f);
    f->id = id;
    f->ext = (uint8_t)ext;
    f->len = (uint8_t)n;
    memcpy(f->data, d, (size_t)n);
    qtail = (qtail + 1) % QMAX;
}

static int unhex(const char *t, uint8_t *out)
{
    int n = 0;
    for (; t[0] && t[1]; t += 2) {
        unsigned v;
        sscanf(t, "%2x", &v);
        out[n++] = (uint8_t)v;
    }
    return n;
}

static void send_consecutive(void)
{
    int off = pending_target >= 0 ? 1 : 0, room = 7 - off, pos = 0;
    while (pos < pending_len) {
        uint8_t d[8];
        int i = 0, n = pending_len - pos < room ? pending_len - pos : room;
        if (off) d[i++] = 0xF1;
        d[i++] = (uint8_t)(0x20 | (pending_seq++ & 0x0F));
        memcpy(d + i, pending + pos, (size_t)n);
        push(pending_resp, pending_ext, d, i + n);
        pos += n;
    }
    pending_len = 0;
}

static void answer(const ecu_entry *e)
{
    uint8_t msg[256], d[8];
    int len = unhex(e->answer, msg), off = e->target >= 0 ? 1 : 0, i = 0;
    if (off) d[i++] = 0xF1; /* BMW: first byte is the receiver (tester F1) */
    if (len <= 7 - off) {
        d[i++] = (uint8_t)len;
        memcpy(d + i, msg, (size_t)len);
        push(e->resp_id, e->ext_id, d, i + len);
        return;
    }
    int first = 6 - off;
    d[i++] = (uint8_t)(0x10 | (len >> 8));
    d[i++] = (uint8_t)(len & 0xFF);
    memcpy(d + i, msg, (size_t)first);
    push(e->resp_id, e->ext_id, d, i + first);
    memcpy(pending, msg + first, (size_t)(len - first));
    pending_len = len - first;
    pending_seq = 1;
    pending_target = e->target;
    pending_resp = e->resp_id;
    pending_fc = e->fc_id;
    pending_ext = e->ext_id;
}

/* -- hal ---------------------------------------------------------------------------- */

void hal_out(const char *s, unsigned n)
{
    while (n) {
        ssize_t w = write(g_master, s, n);
        if (w <= 0) exit(0);
        s += w;
        n -= (unsigned)w;
    }
}

int hal_input_pending(void)
{
    struct pollfd p = {g_master, POLLIN, 0};
    return poll(&p, 1, 0) > 0 && (p.revents & POLLIN);
}

uint32_t hal_millis(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)(t.tv_sec * 1000 + t.tv_nsec / 1000000);
}

int hal_can_config(uint32_t bitrate, uint32_t data_bitrate, int fd, int listen_only)
{
    (void)data_bitrate;
    (void)fd;
    g_bitrate = bitrate;
    g_listen = listen_only;
    return 0;
}

int hal_can_send(const box_frame *f)
{
    if (g_listen) {
        fprintf(stderr, "sim: ERROR, box transmits in listen-only mode\n");
        exit(3);
    }
    if (g_bitrate != 500000) return 0; /* wrong bitrate: nobody answers */
    /* flow control for a pending multi-frame answer? */
    if (pending_len && f->id == pending_fc) {
        int off = pending_target >= 0 ? 1 : 0;
        if ((!off || f->data[0] == pending_target) && (f->data[off] >> 4) == 3) send_consecutive();
        return 0;
    }
    for (const ecu_entry *e = g_car->ecus; e->request; e++) {
        if (e->pins_a != g_pins_a || e->req_id != f->id || e->ext_id != f->ext) continue;
        int off = e->target >= 0 ? 1 : 0;
        if (off && f->data[0] != e->target) continue;
        uint8_t req[8];
        int n = unhex(e->request, req), len = f->data[off] & 0x0F;
        if ((f->data[off] >> 4) == 0 && len == n && memcmp(f->data + off + 1, req, (size_t)n) == 0) {
            answer(e);
            return 0;
        }
    }
    return 0;
}

int hal_can_recv(box_frame *f)
{
    if (g_car->broadcast_id && g_pins_a == g_car->broadcast_pin && g_bitrate == 500000 &&
        hal_millis() - last_broadcast >= 10) {
        uint8_t d[8];
        last_broadcast = hal_millis();
        push(g_car->broadcast_id, 0, d, unhex(g_car->broadcast_data, d));
    }
    if (qhead == qtail) return 0;
    *f = q[qhead];
    qhead = (qhead + 1) % QMAX;
    return 1;
}

int hal_voltage_mv(void) { return 13900; }

int hal_select_pins(int a, int b)
{
    if (!((a == 6 && b == 14) || (a == 12 && b == 13) || (a == 3 && b == 11))) return -1;
    g_pins_a = a;
    return 0;
}

/* -- main ----------------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *name = argc > 1 ? argv[1] : "corsa-e";
    for (unsigned i = 0; i < sizeof CARS / sizeof CARS[0]; i++)
        if (!strcmp(CARS[i].name, name)) g_car = &CARS[i];
    if (!g_car) {
        fprintf(stderr, "unbekanntes Fahrzeug %s (corsa-e, bmw-i3, id4, leaf)\n", name);
        return 2;
    }
    g_master = posix_openpt(O_RDWR | O_NOCTTY);
    if (g_master < 0 || grantpt(g_master) || unlockpt(g_master)) { perror("pty"); return 1; }
    const char *slave = ptsname(g_master);
    int keep = open(slave, O_RDWR | O_NOCTTY); /* keeps the pty alive between connections */
    struct termios t;
    tcgetattr(keep, &t);
    cfmakeraw(&t);
    tcsetattr(keep, TCSANOW, &t);
    printf("%s\n", slave);
    fflush(stdout);

    box_init();
    for (;;) {
        char buf[256];
        struct pollfd p = {g_master, POLLIN, 0};
        if (poll(&p, 1, 1000) <= 0) continue;
        ssize_t n = read(g_master, buf, sizeof buf);
        if (n <= 0) continue;
        for (ssize_t i = 0; i < n; i++) box_input(buf[i]);
    }
}
