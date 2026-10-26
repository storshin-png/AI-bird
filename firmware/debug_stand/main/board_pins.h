#ifndef BOARD_PINS_H
#define BOARD_PINS_H

#include "driver/gpio.h"

/*
 * Промежуточный стенд: один I2S-микрофон и SD по SPI.
 * Перед прошивкой сверить с разводкой. На N16R8 не занимать GPIO 26–37:
 * там flash и octal PSRAM.
 *
 * ICS-43434: вывод L/R на землю, чтобы микрофон был левым слотом.
 * BCLK на осциллографе: 44100 Гц × 64 такта = 2.8224 МГц.
 */

#define DBG_I2S_BCLK GPIO_NUM_4
#define DBG_I2S_WS GPIO_NUM_5
#define DBG_I2S_DIN GPIO_NUM_6

#define DBG_SD_SCK GPIO_NUM_12
#define DBG_SD_MOSI GPIO_NUM_11
#define DBG_SD_MISO GPIO_NUM_13
#define DBG_SD_CS GPIO_NUM_10

/* 24 бита ICS-43434 лежат в старших битах 32-битного слота. */
#define I2S_PCM_SHIFT 16
/* 0 — левый слот, 1 — правый. При L/R на земле микрофон в левом слоте. */
#define I2S_SLOT_INDEX 0

#endif
