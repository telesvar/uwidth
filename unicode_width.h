/*
 * Copyright 2025-2026 Dair Aidarkhanov
 * SPDX-License-Identifier: 0BSD
 */

#ifndef UNICODE_WIDTH_H_
#define UNICODE_WIDTH_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UNICODE_WIDTH_VERSION_MAJOR 17
#define UNICODE_WIDTH_VERSION_MINOR 0
#define UNICODE_WIDTH_VERSION_PATCH 0

typedef enum {
    WIDTH_STATE_DEFAULT,
    WIDTH_STATE_AFTER_CR,
    WIDTH_STATE_RI_ODD,
    WIDTH_STATE_RI_EVEN,
    WIDTH_STATE_ZWJ_PENDING,
    WIDTH_STATE_ZWJ_ACTIVE
} width_state_t;

/*
 * Opaque stream state. The fields are private. A copied state can be continued
 * independently of the original.
 */
typedef struct {
    width_state_t state;
    uint_least32_t prev_codepoint;
    uint_least8_t last_base_width;
    uint_least8_t last_base_is_emoji_variation;
} unicode_width_state_t;

void unicode_width_init(unicode_width_state_t *state);

/*
 * Feed the next code point and return its change to the running width. The
 * result may be negative when the code point changes the presentation of the
 * current cluster. Surrogates and values above U+10FFFF are treated as U+FFFD.
 */
int unicode_width_process(
    unicode_width_state_t *state,
    uint_least32_t codepoint
);

/* Return the terminal escape width for a control, or -1 for other values. */
int unicode_width_control_char(uint_least32_t codepoint);

/* Drop the current stream state. */
void unicode_width_reset(unicode_width_state_t *state);

#ifdef __cplusplus
}
#endif

#endif
