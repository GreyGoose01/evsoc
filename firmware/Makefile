# Host build of the firmware core: simulator for tests and for evsoc without hardware.
# The STM32 build happens in STM32CubeIDE (see README.md).

CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror

evsoc-box-sim: sim/sim.c core/box.c core/box.h core/hal.h
	$(CC) $(CFLAGS) -o $@ sim/sim.c core/box.c

clean:
	rm -f evsoc-box-sim

.PHONY: clean
