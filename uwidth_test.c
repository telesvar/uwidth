/*
 * Copyright 2025-2026 Dair Aidarkhanov
 * SPDX-License-Identifier: Zlib
 */

#include "uwidth.h"

#include <stdio.h>

static int failures;

#define CHECK(expression)                                                     \
    do {                                                                      \
        if (!(expression)) {                                                  \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expression);  \
            ++failures;                                                       \
        }                                                                     \
    } while (0)

#define CHECK_CLUSTER(code_points, profile, expected_width)                   \
    uw_check_cluster(                                                         \
        code_points,                                                          \
        (unsigned int)(sizeof(code_points) / sizeof((code_points)[0])),       \
        profile,                                                              \
        expected_width                                                        \
    )

static void uw_check_cluster(
    const Uwidth_Code_Point *code_points,
    unsigned int length,
    Uwidth_Profile profile,
    uint_least32_t expected_width
)
{
    Uwidth_State state;
    Uwidth_Event event;
    Uwidth_Event_Kind event_kind;
    unsigned int index;

    uwidth_init(&state, profile);
    for (index = 0U; index < length; ++index) {
        CHECK(
            uwidth_push(&state, code_points[index], &event)
            == uwidth_event_none
        );
    }
    event_kind = uwidth_finish(&state, &event);
    CHECK(event_kind == uwidth_event_cluster);
    if (event_kind == uwidth_event_cluster) {
        CHECK(event.width == expected_width);
    }
}

static void uw_test_scalar_widths(void)
{
    const Uwidth_Code_Point latin_small_letter_a[] = {'a'};
    const Uwidth_Code_Point cjk_unified_ideograph[] = {0x4E00UL};
    const Uwidth_Code_Point inverted_exclamation_mark[] = {0x00A1UL};
    const Uwidth_Code_Point combining_acute_accent[] = {0x0301UL};
    const Uwidth_Code_Point left_to_right_mark[] = {0x200EUL};
    const Uwidth_Code_Point highest_noncharacter[] = {0x10FFFFUL};
    const Uwidth_Code_Point replacement_character[] = {0xFFFDUL};
    const Uwidth_Code_Point high_surrogate[] = {0xD800UL};
    const Uwidth_Code_Point above_unicode_range[] = {0x110000UL};
    const Uwidth_Code_Point precomposed_e_with_acute[] = {0x00E9UL};
    const Uwidth_Code_Point decomposed_e_with_acute[] = {'e', 0x0301UL};

    CHECK_CLUSTER(latin_small_letter_a, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(cjk_unified_ideograph, uwidth_profile_narrow, 2U);
    CHECK_CLUSTER(inverted_exclamation_mark, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(inverted_exclamation_mark, uwidth_profile_east_asian, 2U);
    CHECK_CLUSTER(combining_acute_accent, uwidth_profile_narrow, 0U);
    CHECK_CLUSTER(left_to_right_mark, uwidth_profile_narrow, 0U);
    CHECK_CLUSTER(highest_noncharacter, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(replacement_character, uwidth_profile_east_asian, 2U);
    CHECK_CLUSTER(high_surrogate, uwidth_profile_east_asian, 2U);
    CHECK_CLUSTER(above_unicode_range, uwidth_profile_east_asian, 2U);
    CHECK_CLUSTER(precomposed_e_with_acute, uwidth_profile_east_asian, 1U);
    CHECK_CLUSTER(decomposed_e_with_acute, uwidth_profile_east_asian, 1U);
}

static void uw_test_grapheme_boundaries(void)
{
    const Uwidth_Code_Point devanagari_virama_diaeresis_ka[] = {
        0x094DUL,
        0x0308UL,
        0x0915UL
    };
    const Uwidth_Code_Point regional_indicator_pair_ab[] = {
        0x1F1E6UL,
        0x1F1E7UL
    };
    const Uwidth_Code_Point united_states_flag[] = {0x1F1FAUL, 0x1F1F8UL};
    Uwidth_State state;
    Uwidth_Event event;

    CHECK_CLUSTER(devanagari_virama_diaeresis_ka, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(regional_indicator_pair_ab, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(united_states_flag, uwidth_profile_narrow, 2U);

    /* ZWNJ after virama breaks before Devanagari ka. */
    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, 0x094DUL, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x200CUL, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x0915UL, &event) == uwidth_event_cluster);
    CHECK(event.width == 0U);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_cluster);
    CHECK(event.width == 1U);

    /* Regional indicators K and Z form a flag before the following U. */
    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, 0x1F1F0UL, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x1F1FFUL, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x1F1FAUL, &event) == uwidth_event_cluster);
    CHECK(event.width == 2U);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_cluster);
    CHECK(event.width == 1U);
}

static void uw_test_presentation_sequences(void)
{
    const Uwidth_Code_Point copyright_text_presentation[] = {
        0x00A9UL,
        0xFE0EUL
    };
    const Uwidth_Code_Point copyright_emoji_presentation[] = {
        0x00A9UL,
        0xFE0FUL
    };
    const Uwidth_Code_Point digit_one_keycap[] = {'1', 0xFE0FUL, 0x20E3UL};
    const Uwidth_Code_Point woman_technologist_with_combining_acute_accent[] = {
        0x1F469UL,
        0x200DUL,
        0x1F4BBUL,
        0x0301UL
    };

    CHECK_CLUSTER(copyright_text_presentation, uwidth_profile_narrow, 1U);
    CHECK_CLUSTER(copyright_emoji_presentation, uwidth_profile_narrow, 2U);
    CHECK_CLUSTER(digit_one_keycap, uwidth_profile_narrow, 2U);
    CHECK_CLUSTER(
        woman_technologist_with_combining_acute_accent,
        uwidth_profile_narrow,
        2U
    );
}

static void uw_test_stream_state(void)
{
    Uwidth_State state;
    Uwidth_State copied_state;
    Uwidth_Event event;
    Uwidth_Event event_from_copy;

    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 'a', &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 'b', &event) == uwidth_event_cluster);
    CHECK(event.width == 1U);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_cluster);
    CHECK(event.width == 1U);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_none);

    /* A copy taken after woman+ZWJ continues independently of the original. */
    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, 0x1F469UL, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x200DUL, &event) == uwidth_event_none);
    copied_state = state;
    CHECK(uwidth_push(&state, 0x1F4BBUL, &event) == uwidth_event_none);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_cluster);
    CHECK(event.width == 2U);
    CHECK(
        uwidth_push(&copied_state, 'x', &event_from_copy)
        == uwidth_event_cluster
    );
    CHECK(event_from_copy.width == 2U);
    CHECK(
        uwidth_finish(&copied_state, &event_from_copy)
        == uwidth_event_cluster
    );
    CHECK(event_from_copy.width == 1U);

    uwidth_init(&state, uwidth_profile_east_asian);
    CHECK(uwidth_push(&state, 0x00A1UL, &event) == uwidth_event_none);
    uwidth_reset(&state);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, 0x00A1UL, &event) == uwidth_event_none);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_cluster);
    CHECK(event.width == 2U);
}

static void uw_test_controls(void)
{
    Uwidth_State state;
    Uwidth_Event event;

    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, '\r', &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, '\n', &event) == uwidth_event_none);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_control);
    CHECK(event.control == '\r');

    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, 'a', &event) == uwidth_event_none);
    CHECK(uwidth_push(&state, '\t', &event) == uwidth_event_cluster);
    CHECK(event.width == 1U);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_control);
    CHECK(event.control == '\t');

    /* U+0080 is a C1 control event. */
    uwidth_init(&state, uwidth_profile_narrow);
    CHECK(uwidth_push(&state, 0x80UL, &event) == uwidth_event_none);
    CHECK(uwidth_finish(&state, &event) == uwidth_event_control);
    CHECK(event.control == 0x80UL);
}

int main(void)
{
    uw_test_scalar_widths();
    uw_test_grapheme_boundaries();
    uw_test_presentation_sequences();
    uw_test_stream_state();
    uw_test_controls();

    if (failures != 0) {
        fprintf(stderr, "uwidth_test: %d failure(s)\n", failures);
        return 1;
    }
    puts("uwidth_test: all checks passed");
    return 0;
}
