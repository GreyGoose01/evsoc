/* evsoc box on the STM32H723 (NUCLEO-H723ZG): hardware layer for core/box.c.
 *
 * Expects a STM32CubeMX project (see firmware/README.md) with
 *   - FDCAN1 (PD0 RX, PD1 TX), kernel clock e.g. 80 MHz, any timing (set here at runtime)
 *   - USB_OTG_HS as device, CDC class (usbd_cdc_if.c with CDC_Transmit_HS)
 *   - ADC1, one channel at the 47k/10k divider from OBD pin 16, 16-bit resolution
 *   - GPIO outputs with the user labels SILENT1 (and for stage 2 SILENT2, REL_12_13, REL_3_11)
 *   - stage 2 only: FDCAN2 and the define EVSOC_STAGE2
 *
 * Integration (three lines in CubeMX's user code sections):
 *   usbd_cdc_if.c, CDC_Receive_HS():  evsoc_usb_received(Buf, *Len);
 *   main.c, before the main loop:     evsoc_start();
 *   main.c, in the main loop:         evsoc_poll();
 */
#include "main.h"
#include "usbd_cdc_if.h"

#include "../../core/box.h"
#include "../../core/hal.h"

#include <string.h>

extern FDCAN_HandleTypeDef hfdcan1;
extern ADC_HandleTypeDef hadc1;
#ifdef EVSOC_STAGE2
extern FDCAN_HandleTypeDef hfdcan2;
#endif

#define DIVIDER_X10 57u /* (47k + 10k) / 10k = 5.7 */

static FDCAN_HandleTypeDef *g_can = &hfdcan1;
static int g_listen, g_fd;

/* -- USB in: ring buffer filled from the USB interrupt ------------------------------- */

#define RX_SIZE 1024u
static volatile uint8_t rx_ring[RX_SIZE];
static volatile uint32_t rx_head, rx_tail;

void evsoc_usb_received(const uint8_t *buf, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        uint32_t next = (rx_head + 1) % RX_SIZE;
        if (next == rx_tail) return; /* host sends faster than we execute: drop */
        rx_ring[rx_head] = buf[i];
        rx_head = next;
    }
}

int hal_input_pending(void) { return rx_head != rx_tail; }

void evsoc_start(void) { box_init(); }

void evsoc_poll(void)
{
    while (rx_tail != rx_head) {
        char c = (char)rx_ring[rx_tail];
        rx_tail = (rx_tail + 1) % RX_SIZE;
        box_input(c);
    }
}

/* -- USB out ------------------------------------------------------------------------- */

void hal_out(const char *s, unsigned n)
{
    /* Two buffers in turn: when a transfer is accepted, the one before it has finished,
     * so the buffer used two transfers ago is free again. 63 bytes avoid zero-length packets. */
    static uint8_t buf[2][63];
    static unsigned which;
    while (n) {
        unsigned k = n < sizeof buf[0] ? n : sizeof buf[0];
        uint32_t start = HAL_GetTick();
        memcpy(buf[which], s, k);
        while (CDC_Transmit_HS(buf[which], (uint16_t)k) == USBD_BUSY)
            if (HAL_GetTick() - start > 200) return; /* host not reading: give up, keep running */
        which ^= 1u;
        s += k;
        n -= k;
    }
}

uint32_t hal_millis(void) { return HAL_GetTick(); }

/* -- CAN ------------------------------------------------------------------------------ */

static const struct { uint8_t len; uint32_t code; } DLC[] = {
    {0, FDCAN_DLC_BYTES_0},   {1, FDCAN_DLC_BYTES_1},   {2, FDCAN_DLC_BYTES_2},   {3, FDCAN_DLC_BYTES_3},
    {4, FDCAN_DLC_BYTES_4},   {5, FDCAN_DLC_BYTES_5},   {6, FDCAN_DLC_BYTES_6},   {7, FDCAN_DLC_BYTES_7},
    {8, FDCAN_DLC_BYTES_8},   {12, FDCAN_DLC_BYTES_12}, {16, FDCAN_DLC_BYTES_16}, {20, FDCAN_DLC_BYTES_20},
    {24, FDCAN_DLC_BYTES_24}, {32, FDCAN_DLC_BYTES_32}, {48, FDCAN_DLC_BYTES_48}, {64, FDCAN_DLC_BYTES_64},
};

static uint32_t len_to_code(uint8_t *len)
{
    for (unsigned i = 0; i < sizeof DLC / sizeof DLC[0]; i++)
        if (DLC[i].len >= *len) { *len = DLC[i].len; return DLC[i].code; }
    *len = 64;
    return FDCAN_DLC_BYTES_64;
}

static uint8_t code_to_len(uint32_t code)
{
    for (unsigned i = 0; i < sizeof DLC / sizeof DLC[0]; i++)
        if (DLC[i].code == code) return DLC[i].len;
    return 0;
}

static void set_silent(FDCAN_HandleTypeDef *can, int on)
{
    GPIO_PinState st = on ? GPIO_PIN_SET : GPIO_PIN_RESET;
#ifdef EVSOC_STAGE2
    if (can == &hfdcan2) { HAL_GPIO_WritePin(SILENT2_GPIO_Port, SILENT2_Pin, st); return; }
#endif
    (void)can;
    HAL_GPIO_WritePin(SILENT1_GPIO_Port, SILENT1_Pin, st);
}

/* Nominal phase 16 time quanta (1 + 13 + 2, sample point 87.5 %),
 * data phase 20 time quanta (1 + 15 + 4, 80 %). */
int hal_can_config(uint32_t bitrate, uint32_t data_bitrate, int fd, int listen_only)
{
    uint32_t clk = HAL_RCCEx_GetPeriphCLKFreq(RCC_PERIPHCLK_FDCAN);
    if (!bitrate || clk % (bitrate * 16u)) return -1;
    if (fd && (!data_bitrate || clk % (data_bitrate * 20u))) return -1;

    set_silent(g_can, 1); /* transmitter off while reconfiguring */
    HAL_FDCAN_Stop(g_can);
    g_can->Init.FrameFormat = fd ? FDCAN_FRAME_FD_BRS : FDCAN_FRAME_CLASSIC;
    g_can->Init.Mode = listen_only ? FDCAN_MODE_BUS_MONITORING : FDCAN_MODE_NORMAL;
    g_can->Init.AutoRetransmission = ENABLE;
    g_can->Init.TransmitPause = DISABLE;
    g_can->Init.ProtocolException = DISABLE;
    g_can->Init.NominalPrescaler = clk / (bitrate * 16u);
    g_can->Init.NominalSyncJumpWidth = 2;
    g_can->Init.NominalTimeSeg1 = 13;
    g_can->Init.NominalTimeSeg2 = 2;
    g_can->Init.DataPrescaler = fd ? clk / (data_bitrate * 20u) : 1;
    g_can->Init.DataSyncJumpWidth = 4;
    g_can->Init.DataTimeSeg1 = 15;
    g_can->Init.DataTimeSeg2 = 4;
    g_can->Init.StdFiltersNbr = 0;
    g_can->Init.ExtFiltersNbr = 0;
    g_can->Init.RxFifo0ElmtsNbr = 32;
    g_can->Init.RxFifo0ElmtSize = FDCAN_DATA_BYTES_64;
    g_can->Init.RxFifo1ElmtsNbr = 0;
    g_can->Init.RxBuffersNbr = 0;
    g_can->Init.TxEventsNbr = 0;
    g_can->Init.TxBuffersNbr = 0;
    g_can->Init.TxFifoQueueElmtsNbr = 8;
    g_can->Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
    g_can->Init.TxElmtSize = FDCAN_DATA_BYTES_64;
    if (HAL_FDCAN_Init(g_can) != HAL_OK) return -1;
    /* everything into FIFO 0: the core filters itself, like the ELM327 does */
    if (HAL_FDCAN_ConfigGlobalFilter(g_can, FDCAN_ACCEPT_IN_RX_FIFO0, FDCAN_ACCEPT_IN_RX_FIFO0,
                                     FDCAN_REJECT_REMOTE, FDCAN_REJECT_REMOTE) != HAL_OK)
        return -1;
    if (fd) {
        uint32_t tdco = g_can->Init.DataPrescaler * (1u + g_can->Init.DataTimeSeg1);
        HAL_FDCAN_ConfigTxDelayCompensation(g_can, tdco, 0);
        HAL_FDCAN_EnableTxDelayCompensation(g_can);
    }
    if (HAL_FDCAN_Start(g_can) != HAL_OK) return -1;
    g_listen = listen_only;
    g_fd = fd;
    set_silent(g_can, listen_only); /* silent pin: listen-only is guaranteed in hardware too */
    return 0;
}

int hal_can_send(const box_frame *f)
{
    FDCAN_TxHeaderTypeDef h;
    uint8_t data[64] = {0}, len = f->len;
    uint32_t start = HAL_GetTick();
    if (g_listen) return -1;
    memset(&h, 0, sizeof h);
    h.Identifier = f->id;
    h.IdType = f->ext ? FDCAN_EXTENDED_ID : FDCAN_STANDARD_ID;
    h.TxFrameType = FDCAN_DATA_FRAME;
    h.DataLength = len_to_code(&len);
    h.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    h.BitRateSwitch = (f->fd && g_fd) ? FDCAN_BRS_ON : FDCAN_BRS_OFF;
    h.FDFormat = (f->fd && g_fd) ? FDCAN_FD_CAN : FDCAN_CLASSIC_CAN;
    h.TxEventFifoControl = FDCAN_NO_TX_EVENTS;
    h.MessageMarker = 0;
    memcpy(data, f->data, f->len);
    while (HAL_FDCAN_GetTxFifoFreeLevel(g_can) == 0)
        if (HAL_GetTick() - start > 100) return -1; /* bus off or nobody acknowledges */
    return HAL_FDCAN_AddMessageToTxFifoQ(g_can, &h, data) == HAL_OK ? 0 : -1;
}

int hal_can_recv(box_frame *f)
{
    FDCAN_RxHeaderTypeDef h;
    if (HAL_FDCAN_GetRxFifoFillLevel(g_can, FDCAN_RX_FIFO0) == 0) return 0;
    if (HAL_FDCAN_GetRxMessage(g_can, FDCAN_RX_FIFO0, &h, f->data) != HAL_OK) return 0;
    f->id = h.Identifier;
    f->ext = h.IdType == FDCAN_EXTENDED_ID;
    f->fd = h.FDFormat == FDCAN_FD_CAN;
    f->len = code_to_len(h.DataLength);
    return 1;
}

/* -- 12 V and pins ---------------------------------------------------------------------- */

int hal_voltage_mv(void)
{
    uint32_t sum = 0;
    for (int i = 0; i < 8; i++) {
        if (HAL_ADC_Start(&hadc1) != HAL_OK || HAL_ADC_PollForConversion(&hadc1, 10) != HAL_OK) return -1;
        sum += HAL_ADC_GetValue(&hadc1);
        HAL_ADC_Stop(&hadc1);
    }
    /* 16-bit result, 3.3 V reference */
    return (int)((sum / 8u) * 3300u / 65535u * DIVIDER_X10 / 10u);
}

int hal_select_pins(int a, int b)
{
    if (a == 6 && b == 14) {
#ifdef EVSOC_STAGE2
        HAL_GPIO_WritePin(REL_12_13_GPIO_Port, REL_12_13_Pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(REL_3_11_GPIO_Port, REL_3_11_Pin, GPIO_PIN_RESET);
#endif
        g_can = &hfdcan1;
        return 0;
    }
#ifdef EVSOC_STAGE2
    if ((a == 12 && b == 13) || (a == 3 && b == 11)) {
        int k1 = a == 12;
        /* never both relays: first open, then close the wanted one */
        HAL_GPIO_WritePin(REL_12_13_GPIO_Port, REL_12_13_Pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(REL_3_11_GPIO_Port, REL_3_11_Pin, GPIO_PIN_RESET);
        HAL_Delay(5); /* contacts release */
        if (k1) HAL_GPIO_WritePin(REL_12_13_GPIO_Port, REL_12_13_Pin, GPIO_PIN_SET);
        else HAL_GPIO_WritePin(REL_3_11_GPIO_Port, REL_3_11_Pin, GPIO_PIN_SET);
        HAL_Delay(5); /* contacts settle */
        g_can = &hfdcan2;
        return 0;
    }
#endif
    return -1;
}
