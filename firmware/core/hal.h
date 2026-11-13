/* Hardware interface of the evsoc box firmware.
 *
 * The core (box.c) only talks to the hardware through these functions. They are
 * implemented once for the STM32H723 (port/stm32h7) and once for the host simulator
 * (sim/), which lets evsoc and the tests talk to the real firmware logic on a PC.
 */
#ifndef EVSOC_HAL_H
#define EVSOC_HAL_H

#include <stdint.h>

typedef struct {
    uint32_t id;
    uint8_t ext;        /* 1 = 29-bit identifier */
    uint8_t fd;         /* 1 = CAN-FD frame (up to 64 data bytes) */
    uint8_t len;
    uint8_t data[64];
} box_frame;

/* Bytes to the host (USB CDC). Must send everything before returning. */
void hal_out(const char *s, unsigned n);

/* 1 if the host sent bytes that box_input() has not seen yet (stops ATMA). */
int hal_input_pending(void);

uint32_t hal_millis(void);

/* (Re)configure the CAN channel that is switched to the OBD pins.
 * data_bitrate is only used with fd = 1. listen_only = 1: no ACK, no error frames,
 * no transmission (the transceiver's silent pin is set as well). Returns 0 on success. */
int hal_can_config(uint32_t bitrate, uint32_t data_bitrate, int fd, int listen_only);

/* Returns 0 if the frame was queued. */
int hal_can_send(const box_frame *f);

/* Returns 1 and fills f if a received frame is waiting. Never blocks. */
int hal_can_recv(box_frame *f);

/* 12 V supply at OBD pin 16 in millivolts, or -1 without measurement. */
int hal_voltage_mv(void);

/* Connect the CAN channel to the OBD pin pair (a, b). Returns 0 on success,
 * -1 if this hardware cannot reach these pins. */
int hal_select_pins(int a, int b);

#endif
