/* evsoc box firmware core: ELM327 command subset + EVS commands (docs/box-protocol.md). */
#ifndef EVSOC_BOX_H
#define EVSOC_BOX_H

#include <stddef.h>
#include <stdint.h>

#define BOX_VERSION "0.1"

/* Reset all settings (power-up state, CAN at 500 kbit/s on pins 6/14). */
void box_init(void);

/* Feed one byte from the host. A complete command (CR) is executed right away;
 * the call may block until the vehicle answered or the timeout expired. */
void box_input(char c);

/* Read-only filter: 1 if this diagnostic request may be sent (also used by the tests). */
int box_request_allowed(const uint8_t *req, size_t len);

#endif
