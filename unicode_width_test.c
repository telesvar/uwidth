/*
 * Copyright 2025-2026 Dair Aidarkhanov
 * SPDX-License-Identifier: 0BSD
 */

#include "unicode_width.h"

#include <stdio.h>

static int failures;

#define CHECK(expression)                                                     \
    do {                                                                      \
        if (!(expression)) {                                                  \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expression);  \
            ++failures;                                                       \
        }                                                                     \
    } while (0)

#define CHECK_WIDTH(code_points, expected_width)                              \
    uw_check_width(                                                           \
        code_points,                                                          \
        (unsigned int)(sizeof(code_points) / sizeof((code_points)[0])),       \
        expected_width                                                        \
    )

static void uw_check_width(
    const uint_least32_t *code_points,
    unsigned int length,
    int expected_width
)
{
    unicode_width_state_t state;
    unsigned int index;
    int total;

    total = 0;
    unicode_width_init(&state);
    for (index = 0U; index < length; ++index) {
        int delta;

        delta = unicode_width_process(&state, code_points[index]);
        if (delta >= 0 || unicode_width_control_char(code_points[index]) < 0) {
            total += delta;
        }
    }
    CHECK(total == expected_width);
}

static void uw_test_scalar_widths(void)
{
    uint_least32_t ascii_letters[] = {'a', 'b', 'c'};
    uint_least32_t cjk_unified_ideograph[] = {0x4E00UL};
    uint_least32_t inverted_exclamation_mark[] = {0x00A1UL};
    uint_least32_t combining_acute_accent[] = {0x0301UL};
    uint_least32_t zero_width_joiner[] = {0x200DUL};
    uint_least32_t noncharacter[] = {0xFDD0UL};
    uint_least32_t replacement_character[] = {0xFFFDUL};
    uint_least32_t high_surrogate[] = {0xD800UL};
    uint_least32_t above_unicode_range[] = {0x110000UL};

    CHECK_WIDTH(ascii_letters, 3);
    CHECK_WIDTH(cjk_unified_ideograph, 2);
    CHECK_WIDTH(inverted_exclamation_mark, 1);
    CHECK_WIDTH(combining_acute_accent, 0);
    CHECK_WIDTH(zero_width_joiner, 0);
    CHECK_WIDTH(noncharacter, 1);
    CHECK_WIDTH(replacement_character, 1);
    CHECK_WIDTH(high_surrogate, 1);
    CHECK_WIDTH(above_unicode_range, 1);
}

static void uw_test_canonical_equivalence(void)
{
    uint_least32_t precomposed_e_with_acute[] = {0x00E9UL};
    uint_least32_t decomposed_e_with_acute[] = {'e', 0x0301UL};
    uint_least32_t hangul_syllable_gag[] = {0xAC01UL};
    uint_least32_t decomposed_hangul_syllable_gag[] = {
        0x1100UL,
        0x1161UL,
        0x11A8UL
    };

    CHECK_WIDTH(precomposed_e_with_acute, 1);
    CHECK_WIDTH(decomposed_e_with_acute, 1);
    CHECK_WIDTH(hangul_syllable_gag, 2);
    CHECK_WIDTH(decomposed_hangul_syllable_gag, 2);
}

static void uw_test_grapheme_boundaries(void)
{
    uint_least32_t devanagari_ka_virama_ssa[] = {
        0x0915UL,
        0x094DUL,
        0x0937UL
    };
    uint_least32_t regional_indicator_pair_ab[] = {0x1F1E6UL, 0x1F1E7UL};
    uint_least32_t united_states_flag[] = {0x1F1FAUL, 0x1F1F8UL};
    uint_least32_t united_states_and_canada_flags[] = {
        0x1F1FAUL,
        0x1F1F8UL,
        0x1F1E8UL,
        0x1F1E6UL
    };

    CHECK_WIDTH(devanagari_ka_virama_ssa, 1);
    CHECK_WIDTH(regional_indicator_pair_ab, 1);
    CHECK_WIDTH(united_states_flag, 2);
    CHECK_WIDTH(united_states_and_canada_flags, 4);
}

static void uw_test_presentation_sequences(void)
{
    uint_least32_t woman_technologist_with_combining_acute_accent[] = {
        0x1F469UL,
        0x200DUL,
        0x1F4BBUL,
        0x0301UL
    };
    uint_least32_t person_zwj_latin_small_letter_x[] = {
        0x1F9D1UL,
        0x200DUL,
        'x'
    };
    uint_least32_t digit_one_keycap[] = {'1', 0xFE0FUL, 0x20E3UL};
    uint_least32_t england_subdivision_flag[] = {
        0x1F3F4UL,
        0xE0067UL,
        0xE0062UL,
        0xE0065UL,
        0xE006EUL,
        0xE0067UL,
        0xE007FUL
    };
    unicode_width_state_t state;

    CHECK_WIDTH(woman_technologist_with_combining_acute_accent, 2);
    CHECK_WIDTH(person_zwj_latin_small_letter_x, 3);
    CHECK_WIDTH(digit_one_keycap, 2);
    CHECK_WIDTH(england_subdivision_flag, 2);

    /* A text variation selector narrows the copyright sign from 2 to 1. */
    unicode_width_init(&state);
    CHECK(unicode_width_process(&state, 0x00A9UL) == 2);
    CHECK(unicode_width_process(&state, 0xFE0EUL) == -1);
    CHECK(unicode_width_control_char(0xFE0EUL) == -1);
}

static void uw_test_controls(void)
{
    uint_least32_t separated_regional_indicators[] = {
        0x1F1E6UL,
        '\a',
        0x1F1E7UL
    };
    unicode_width_state_t state;

    /* C0, DEL, C1, and printable ASCII. */
    CHECK(unicode_width_control_char(0x01UL) == 2);
    CHECK(unicode_width_control_char(0x7FUL) == 2);
    CHECK(unicode_width_control_char(0x90UL) == 4);
    CHECK(unicode_width_control_char('A') == -1);
    CHECK_WIDTH(separated_regional_indicators, 2);

    unicode_width_init(&state);
    CHECK(unicode_width_process(&state, '\a') == -1);
    CHECK(unicode_width_process(&state, '\r') == 0);
    CHECK(unicode_width_process(&state, '\n') == 0);
}

static void uw_test_state_copy_and_reset(void)
{
    unicode_width_state_t original;
    unicode_width_state_t copied_state;
    int text_presentation_adjustment;
    int emoji_presentation_adjustment;

    /* A copy taken after the copyright sign continues independently. */
    unicode_width_init(&original);
    CHECK(unicode_width_process(&original, 0x00A9UL) == 2);
    copied_state = original;
    text_presentation_adjustment = unicode_width_process(&original, 0xFE0EUL);
    emoji_presentation_adjustment = unicode_width_process(
        &copied_state,
        0xFE0FUL
    );
    CHECK(text_presentation_adjustment == -1);
    CHECK(emoji_presentation_adjustment == 0);

    unicode_width_reset(&original);
    CHECK(unicode_width_process(&original, 'A') == 1);
}

int main(void)
{
    uw_test_scalar_widths();
    uw_test_canonical_equivalence();
    uw_test_grapheme_boundaries();
    uw_test_presentation_sequences();
    uw_test_controls();
    uw_test_state_copy_and_reset();

    if (failures != 0) {
        fprintf(stderr, "unicode_width_test: %d failure(s)\n", failures);
        return 1;
    }
    puts("unicode_width_test: all checks passed");
    return 0;
}
