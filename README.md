# unicode-width

`unicode-width` measures the display width of a stream of Unicode code points
in terminal columns using Unicode 17.0.0 data. It is written in C89.

## Using the library

Add `unicode_width.h` and `unicode_width.c` to your project. Initialize a
`unicode_width_state_t`, then feed each code point with `unicode_width_process`.

The API uses a fixed narrow profile, so East Asian Ambiguous characters have
width 1.

Each call to `unicode_width_process` returns the change in width caused by the
new scalar. The delta may be negative when later input revises the presentation
of the current cluster. For example, VS15 can turn an emoji presentation from
width 2 to width 1 by returning `-1`. Surrogates and values above U+10FFFF are
treated as U+FFFD. Noncharacters are accepted as ordinary scalars.

Most control characters also return `-1` from `unicode_width_process`. Use
`unicode_width_control_char` to tell those apart from a real width correction:

- `2` for C0 controls and DEL
- `4` for C1 controls
- `-1` for everything else

CR and LF return `0` from `unicode_width_process`.

`unicode_width_reset` starts a new stream. A copied `unicode_width_state_t` can
be continued independently of the original.

Example: sum width changes and ignore controls.

```c
#include "unicode_width.h"

static int measure(const uint_least32_t *text, unsigned int length)
{
    unicode_width_state_t state;
    unsigned int index;
    int width = 0;

    unicode_width_init(&state);
    for (index = 0U; index < length; ++index) {
        int delta = unicode_width_process(&state, text[index]);

        if (unicode_width_control_char(text[index]) < 0) {
            width += delta;
        }
    }
    return width;
}
```

The running total already includes the pending cluster, so this API has no
finish function.

## Unicode behavior

Grapheme boundaries follow
[UAX #29](https://www.unicode.org/reports/tr29/tr29-47.html), canonical
decomposition follows [UAX #15](https://www.unicode.org/reports/tr15/), and
ordinary width follows [UAX #11](https://www.unicode.org/reports/tr11/).
Emoji and text presentation use the sequences defined by
[UTS #51](https://www.unicode.org/reports/tr51/).

## Generating and testing

Regenerating or checking the tables needs Python 3.9 or later. The generator
reads the Unicode version macros from `unicode_width.h`.

```sh
python3 generate.py
python3 generate.py --check
```

Build and run the tests:

```sh
cc -std=c89 -Wall -Wextra -Werror -O2 \
    unicode_width.c unicode_width_test.c -o unicode_width_test
./unicode_width_test
```

## License

unicode-width combines code licensed under the
[Zero-Clause BSD License](https://opensource.org/license/0bsd) with tables
derived from Unicode data licensed under the
[Unicode License v3](https://www.unicode.org/license.txt).
