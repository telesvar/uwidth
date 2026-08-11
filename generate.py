#!/usr/bin/env python3
#
# Copyright 2025-2026 Dair Aidarkhanov
# SPDX-License-Identifier: 0BSD

"""Build unicode_width.c from Unicode data and unicode_width.c.in."""

import argparse
import hashlib
import os
import tempfile
import urllib.request
from array import array
from pathlib import Path


# Configuration

project_root = Path(__file__).resolve().parent
template_path = project_root / "unicode_width.c.in"
output_path = project_root / "unicode_width.c"
header_path = project_root / "unicode_width.h"
# Unicode version comes from unicode_width.h so the C API and the tables always
# describe the same release.
header_defines = {
    fields[1]: fields[2]
    for line in header_path.read_text(encoding="utf-8").splitlines()
    if len(fields := line.split()) == 3 and fields[0] == "#define"
}
unicode_version = ".".join(
    header_defines[name]
    for name in (
        "UNICODE_WIDTH_VERSION_MAJOR",
        "UNICODE_WIDTH_VERSION_MINOR",
        "UNICODE_WIDTH_VERSION_PATCH",
    )
)
unicode_limit = 0x110000

property_run_block = 16
property_page_shift = 12
property_dictionary_index_bits = 5
property_dictionary_index_mask = (1 << property_dictionary_index_bits) - 1

encoded_u16_bytes = 2
encoded_u21_bytes = 3
checkpoint_bytes = encoded_u21_bytes + encoded_u16_bytes

dfa_root_block = 16
dfa_offset_bits = 14
dfa_action_shift = dfa_offset_bits
dfa_offset_limit = 1 << dfa_offset_bits
dfa_offset_mask = dfa_offset_limit - 1
dfa_dead = 0xFF

unicode_sources = {
    "DerivedCoreProperties.txt": (
        "ucd/DerivedCoreProperties.txt",
        "24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08",
    ),
    "DerivedEastAsianWidth.txt": (
        "ucd/extracted/DerivedEastAsianWidth.txt",
        "0b5523a2217cb318d20b329a05d31eec5af5686ba09d263b85bb75a28989a3a8",
    ),
    "GraphemeBreakProperty.txt": (
        "ucd/auxiliary/GraphemeBreakProperty.txt",
        "d6b51d1d2ae5c33b451b7ed994b48f1f4dc62b2272a5831e7fd418514a6bae89",
    ),
    "UnicodeData.txt": (
        "ucd/UnicodeData.txt",
        "2e1efc1dcb59c575eedf5ccae60f95229f706ee6d031835247d843c11d96470c",
    ),
    "emoji-data.txt": (
        "ucd/emoji/emoji-data.txt",
        "2cb2bb9455cda83e8481541ecf5b6dfda66a3bb89efa3fa7c5297eccf607b72b",
    ),
    "emoji-test.txt": (
        "emoji/emoji-test.txt",
        "1d8a944f88d7952f7ef7c5167fef3c67995bcae24543949710231b03a201acda",
    ),
    "emoji-variation-sequences.txt": (
        "ucd/emoji/emoji-variation-sequences.txt",
        "bb3d09ef03f206012c7532dd52dc0a21c9efddba0135ea4cf0d9201b8b9bba7e",
    ),
}
# Cache directory includes a short hash of the pinned file digests so a hash
# bump fetches into a new folder instead of reusing stale files.
unicode_data_revision = hashlib.sha256(
    "".join(
        unicode_sources[name][1] for name in sorted(unicode_sources)
    ).encode()
).hexdigest()[:12]
unicode_data_directory = (
    project_root / ".unicode-data" / f"{unicode_version}-{unicode_data_revision}"
)

# Encoded property values

grapheme_break_mask = 0x0F
extended_pictographic_bit = 0x10
indic_conjunct_break_shift = 5
indic_conjunct_break_mask = 0x03
contribution_shift = 7
contribution_mask = 0x03
dfa_start_bit = 0x0200
ascii_limit = 0x80
ascii_printable_first = 0x20
ascii_printable_last = 0x7E
cr_code_point = 0x0D
lf_code_point = 0x0A

grapheme_break_values = {
    "Other": 0,
    "CR": 1,
    "LF": 2,
    "Control": 3,
    "Extend": 4,
    "ZWJ": 5,
    "Regional_Indicator": 6,
    "Prepend": 7,
    "SpacingMark": 8,
    "L": 9,
    "V": 10,
    "T": 11,
    "LV": 12,
    "LVT": 13,
}
cc_grapheme_break = 14

indic_conjunct_break_values = {
    "None": 0,
    "Extend": 1,
    "Linker": 2,
    "Consonant": 3,
}

width_none = 0
width_narrow = 1
width_ambiguous = 2
width_wide = 3

action_none = 0
action_emoji = 1
action_text = 2

emoji_stage_none = 0
emoji_stage_extended_pictographic = 1
emoji_stage_zwj = 2
emoji_stage_mask = 0x03


# Unicode data

def sha256_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_unicode_sources(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"https://www.unicode.org/Public/{unicode_version}/"
    source_paths = {}
    for name, (relative_url, expected_hash) in unicode_sources.items():
        path = data_dir / name
        if path.exists():
            if sha256_digest(path) != expected_hash:
                raise ValueError(f"{path}: SHA-256 mismatch")
        else:
            url = base_url + relative_url
            print(f"downloading {url}")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=name + ".",
                dir=str(data_dir),
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                urllib.request.urlretrieve(url, temporary)
                if sha256_digest(temporary) != expected_hash:
                    raise ValueError(f"{name}: SHA-256 mismatch")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        source_paths[name] = path
    return source_paths


# Unicode property loading

def parse_range(field):
    lower, separator, upper = field.partition("..")
    lower = int(lower, 16)
    return lower, int(upper, 16) if separator else lower


def property_records(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            body = line.partition("#")[0].strip()
            if not body:
                continue
            fields = tuple(field.strip() for field in body.split(";"))
            lower, upper = parse_range(fields[0])
            yield lower, upper, fields[1:]


# @missing lines set defaults for ranges the file body omits. Loaders apply
# them first. Explicit records then override.
def missing_records(path):
    prefix = "# @missing:"
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line.startswith(prefix):
                continue
            fields = tuple(field.strip() for field in line[len(prefix) :].split(";"))
            lower, upper = parse_range(fields[0])
            yield lower, upper, fields[1:]


def fill_range(values, lower, upper, value):
    values[lower : upper + 1] = bytes([value]) * (upper - lower + 1)


def load_grapheme_break_classes(path):
    values = bytearray([grapheme_break_values["Other"]]) * unicode_limit
    for lower, upper, (value,) in missing_records(path):
        fill_range(values, lower, upper, grapheme_break_values[value])
    for lower, upper, (value,) in property_records(path):
        fill_range(values, lower, upper, grapheme_break_values[value])
    return values


def load_derived_core_properties(path):
    default_ignorable = bytearray(unicode_limit)
    grapheme_extend = bytearray(unicode_limit)
    indic_conjunct_break = bytearray([indic_conjunct_break_values["None"]]) * unicode_limit

    for lower, upper, fields in missing_records(path):
        if fields[0] == "InCB":
            fill_range(indic_conjunct_break, lower, upper, indic_conjunct_break_values[fields[1]])

    for lower, upper, fields in property_records(path):
        if fields == ("Default_Ignorable_Code_Point",):
            fill_range(default_ignorable, lower, upper, 1)
        elif fields == ("Grapheme_Extend",):
            fill_range(grapheme_extend, lower, upper, 1)
        elif fields[0] == "InCB":
            fill_range(indic_conjunct_break, lower, upper, indic_conjunct_break_values[fields[1]])

    return default_ignorable, grapheme_extend, indic_conjunct_break


def load_east_asian_width(path):
    widths = {
        "N": width_narrow,
        "Neutral": width_narrow,
        "Na": width_narrow,
        "H": width_narrow,
        "A": width_ambiguous,
        "W": width_wide,
        "Wide": width_wide,
        "F": width_wide,
    }
    values = bytearray([width_narrow]) * unicode_limit
    for lower, upper, (value,) in missing_records(path):
        fill_range(values, lower, upper, widths[value])
    for lower, upper, (value,) in property_records(path):
        fill_range(values, lower, upper, widths[value])
    return values


def load_extended_pictographic(path):
    values = bytearray(unicode_limit)
    for lower, upper, (property_name,) in property_records(path):
        if property_name == "Extended_Pictographic":
            fill_range(values, lower, upper, 1)
    return values


# Canonical decomposition and width contributions

hangul_s_base = 0xAC00
hangul_l_base = 0x1100
hangul_v_base = 0x1161
hangul_t_base = 0x11A7
hangul_l_count = 19
hangul_v_count = 21
hangul_t_count = 28
hangul_n_count = hangul_v_count * hangul_t_count
hangul_s_count = hangul_l_count * hangul_n_count
hangul_s_limit = hangul_s_base + hangul_s_count


def parse_canonical_decomposition(fields):
    field = fields[5]
    if not field or field.startswith("<"):
        return None
    return tuple(int(item, 16) for item in field.split())


def apply_unicode_data_range(
    lower,
    upper,
    fields,
    controls,
    decompositions,
):
    decomposition = parse_canonical_decomposition(fields)
    if fields[2] == "Cc":
        fill_range(controls, lower, upper, 1)
    if decomposition is not None:
        for code_point in range(lower, upper + 1):
            decompositions[code_point] = decomposition


def load_unicode_data(path):
    controls = bytearray(unicode_limit)
    decompositions = {}
    pending = None

    with path.open(encoding="utf-8") as stream:
        for line in stream:
            fields = line.rstrip("\n").split(";")
            code_point = int(fields[0], 16)
            name = fields[1]
            # UnicodeData packs some ranges as First/Last pairs. The First row
            # supplies the fields for every code point through Last.
            if name.endswith(", First>"):
                pending = code_point, fields
            elif name.endswith(", Last>"):
                lower, range_fields = pending
                apply_unicode_data_range(
                    lower,
                    code_point,
                    range_fields,
                    controls,
                    decompositions,
                )
                pending = None
            else:
                apply_unicode_data_range(
                    code_point,
                    code_point,
                    fields,
                    controls,
                    decompositions,
                )

    return controls, decompositions


def hangul_decomposition(code_point):
    syllable = code_point - hangul_s_base
    parts = [
        hangul_l_base + syllable // hangul_n_count,
        hangul_v_base + (syllable % hangul_n_count) // hangul_t_count,
    ]
    if syllable % hangul_t_count:
        parts.append(hangul_t_base + syllable % hangul_t_count)
    return tuple(parts)


def decompose_code_point(code_point, decompositions, decomposition_cache):
    cached = decomposition_cache.get(code_point)
    if cached is not None:
        return cached
    # Hangul syllables use the algorithmic decomposition from the standard.
    # UnicodeData does not list those mappings.
    if hangul_s_base <= code_point < hangul_s_limit:
        parts = hangul_decomposition(code_point)
    elif code_point in decompositions:
        parts = decompositions[code_point]
    else:
        return (code_point,)
    result = tuple(
        item
        for part in parts
        for item in decompose_code_point(part, decompositions, decomposition_cache)
    )
    decomposition_cache[code_point] = result
    return result


def derive_width_contributions(
    east_asian_width,
    zero_width,
    decompositions,
):
    width_contributions = bytearray(east_asian_width)
    for code_point in range(unicode_limit):
        if zero_width[code_point]:
            width_contributions[code_point] = width_none

    decomposition_cache = {}

    # A code point with a canonical decomposition inherits the widest
    # contribution among its parts, so width stays stable under normalization.
    def contribution(code_point):
        cached = decomposition_cache.get(code_point)
        if cached is not None:
            return cached
        if hangul_s_base <= code_point < hangul_s_limit:
            parts = hangul_decomposition(code_point)
        elif code_point in decompositions:
            parts = decompositions[code_point]
        else:
            return width_contributions[code_point]
        value = max(contribution(part) for part in parts)
        decomposition_cache[code_point] = value
        return value

    for code_point in decompositions:
        width_contributions[code_point] = contribution(code_point)
    for code_point in range(hangul_s_base, hangul_s_limit):
        width_contributions[code_point] = contribution(code_point)
    return width_contributions


# Emoji presentation sequences

ascii_keycap_starters = (0x23, 0x2A, *range(0x30, 0x3A))


def presentation_sequence_records(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            body = line.partition("#")[0].strip()
            if not body:
                continue
            fields = tuple(field.strip() for field in body.split(";"))
            yield fields[0], fields[1]


def parse_code_point_sequence(field):
    return tuple(int(item, 16) for item in field.split())


def load_presentation_sequences(source_paths, decompositions):
    presentation_sequences = {}
    for sequence_field, _ in presentation_sequence_records(
        source_paths["emoji-test.txt"]
    ):
        sequence = parse_code_point_sequence(sequence_field)
        presentation_sequences[sequence] = action_emoji

    actions = {
        "text style": action_text,
        "emoji style": action_emoji,
    }
    for sequence_field, style in presentation_sequence_records(
        source_paths["emoji-variation-sequences.txt"]
    ):
        presentation_sequences[parse_code_point_sequence(sequence_field)] = (
            actions[style]
        )

    decomposition_cache = {}
    # A code point with a canonical decomposition inherits the singleton
    # presentation action of its first component, so presentation stays stable
    # under canonical normalization.
    singleton_actions = {
        sequence[0]: action
        for sequence, action in presentation_sequences.items()
        if len(sequence) == 1
    }
    for code_point in decompositions:
        decomposition = decompose_code_point(
            code_point,
            decompositions,
            decomposition_cache,
        )
        action = singleton_actions.get(decomposition[0])
        if action is not None:
            presentation_sequences[(code_point,)] = action
    return presentation_sequences


# Runtime properties

# Property word layout: grapheme break in bits 0-3, Extended_Pictographic in
# bit 4, Indic_Conjunct_Break in bits 5-6, width contribution in bits 7-8, and
# the presentation-sequence starter flag in bit 9.
def code_point_property_word(
    grapheme_break,
    extended_pictographic,
    indic_conjunct_break,
    controls,
    width_contributions,
    presentation_sequence_starters,
    code_point,
):
    cluster_break = grapheme_break[code_point]
    # Private grapheme class for Cc controls other than CR and LF. Breaks still
    # follow GCB Control. These Cc points return -1. CR and LF return 0.
    if controls[code_point] and cluster_break == grapheme_break_values["Control"]:
        cluster_break = cc_grapheme_break
    return (
        cluster_break
        | (extended_pictographic[code_point] * extended_pictographic_bit)
        | (indic_conjunct_break[code_point] << indic_conjunct_break_shift)
        | (width_contributions[code_point] << contribution_shift)
        | (dfa_start_bit if code_point in presentation_sequence_starters else 0)
    )


def find_ascii_keycap_dfa_state(
    states,
    transitions,
    root,
    root_checkpoints,
):
    return dfa_transition(
        root,
        ascii_keycap_starters[0],
        states,
        transitions,
        root,
        root_checkpoints,
    )


# Binary encoding helpers

def encode_uleb(value, output):
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)


def decode_uleb(data, offset):
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def append_16(output, value):
    output.extend((value & 0xFF, (value >> 8) & 0xFF))


def append_21(output, value):
    output.extend(
        (
            value & 0xFF,
            (value >> 8) & 0xFF,
            (value >> 16) & 0x1F,
        )
    )


def read_16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def read_21(data, offset):
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)


# Code point property table

def decode_property_runs(checkpoints, stream, run_count):
    decoded = []
    block_count = (run_count + property_run_block - 1) // property_run_block
    for block in range(block_count):
        checkpoint = block * checkpoint_bytes
        start = read_21(checkpoints, checkpoint)
        offset = read_16(checkpoints, checkpoint + encoded_u21_bytes)
        count = min(
            property_run_block,
            run_count - block * property_run_block,
        )
        previous = start
        for index in range(count):
            packed, offset = decode_uleb(stream, offset)
            run_start = previous + (packed >> property_dictionary_index_bits)
            decoded.append(
                (run_start, packed & property_dictionary_index_mask)
            )
            previous = run_start
    return decoded


# Store a run only where the property changes. Each run packs a dictionary
# index in the low bits and a start delta in the rest. Pages narrow checkpoint
# search. Each checkpoint starts one fixed-size block of runs.
def encode_property_table(
    grapheme_break,
    extended_pictographic,
    indic_conjunct_break,
    controls,
    width_contributions,
    presentation_sequence_starters,
):
    values = array(
        "H",
        (
            code_point_property_word(
                grapheme_break,
                extended_pictographic,
                indic_conjunct_break,
                controls,
                width_contributions,
                presentation_sequence_starters,
                code_point,
            )
            for code_point in range(unicode_limit)
        ),
    )
    dictionary = sorted(set(values))
    if len(dictionary) > property_dictionary_index_mask + 1:
        raise ValueError(
            "code point property dictionary needs more than "
            f"{property_dictionary_index_bits} bits"
        )
    dictionary_index = {value: index for index, value in enumerate(dictionary)}

    runs = []
    previous = None
    for code_point, value in enumerate(values):
        if value != previous:
            runs.append((code_point, dictionary_index[value]))
            previous = value

    dictionary_bytes = bytearray()
    for value in dictionary:
        append_16(dictionary_bytes, value)

    checkpoints = bytearray()
    stream = bytearray()
    for block in range(0, len(runs), property_run_block):
        start = runs[block][0]
        if len(stream) > 0xFFFF:
            raise ValueError(
                "code point stream offset no longer fits in 16 bits"
            )
        append_21(checkpoints, start)
        append_16(checkpoints, len(stream))
        previous = start
        for index in range(block, min(block + property_run_block, len(runs))):
            run_start, value = runs[index]
            delta = 0 if index == block else run_start - previous
            encode_uleb(
                (delta << property_dictionary_index_bits) | value,
                stream,
            )
            previous = run_start

    pages = bytearray()
    page_size = 1 << property_page_shift
    checkpoint_count = len(checkpoints) // checkpoint_bytes
    checkpoint = 0
    for page_start in range(0, unicode_limit + page_size, page_size):
        while (
            checkpoint + 1 < checkpoint_count
            and read_21(
                checkpoints,
                (checkpoint + 1) * checkpoint_bytes,
            )
            <= page_start
        ):
            checkpoint += 1
        if checkpoint > 0xFF:
            raise ValueError(
                "code point page checkpoint no longer fits in one byte"
            )
        pages.append(checkpoint)

    if decode_property_runs(checkpoints, stream, len(runs)) != runs:
        raise ValueError("property table encoding failed")
    return dictionary_bytes, checkpoints, stream, pages, len(runs)


# Emoji presentation DFA

# Build a trie, then merge states that share the same action and edges.
# Walk in reverse so every child already has its final state number.
def minimize_dfa(presentation_sequences):
    trie = [{"action": action_none, "edges": {}}]
    for sequence, action in sorted(presentation_sequences.items()):
        state = 0
        for code_point in sequence:
            edges = trie[state]["edges"]
            if code_point not in edges:
                edges[code_point] = len(trie)
                trie.append({"action": action_none, "edges": {}})
            state = edges[code_point]
        trie[state]["action"] = action

    signatures = {}
    old_to_new = {}
    states = []
    for old_state in range(len(trie) - 1, -1, -1):
        signature = (
            trie[old_state]["action"],
            tuple(
                (code_point, old_to_new[target])
                for code_point, target in sorted(trie[old_state]["edges"].items())
            ),
        )
        state = signatures.get(signature)
        if state is None:
            state = len(states)
            signatures[signature] = state
            states.append(signature)
        old_to_new[old_state] = state

    if len(states) > dfa_dead:
        raise ValueError("DFA state no longer fits in one byte")
    root = old_to_new[0]
    return states, root


def transition_ranges(edges):
    ranges = []
    current_range = None
    for code_point, target in edges:
        if (
            current_range is not None
            and code_point == current_range[1] + 1
            and target == current_range[2]
        ):
            current_range[1] = code_point
        else:
            current_range = [code_point, code_point, target]
            ranges.append(current_range)
    return ranges


def dfa_entry(states, state):
    return read_16(states, state * encoded_u16_bytes)


def dfa_offset(states, state):
    return dfa_entry(states, state) & dfa_offset_mask


def dfa_action(states, state):
    return dfa_entry(states, state) >> dfa_action_shift


def decode_dfa_ranges(states, transitions, state):
    offset = dfa_offset(states, state)
    end = dfa_offset(states, state + 1)
    previous = -1
    ranges = []
    while offset < end:
        gap, offset = decode_uleb(transitions, offset)
        span, offset = decode_uleb(transitions, offset)
        target = transitions[offset]
        offset += 1
        lower = previous + 1 + gap
        upper = lower + span
        ranges.append((lower, upper, target))
        previous = upper
    return ranges


def dfa_transition(
    state,
    code_point,
    states,
    transitions,
    root,
    root_checkpoints,
):
    if state == dfa_dead:
        return dfa_dead
    end = dfa_offset(states, state + 1)
    known_start = None

    if state == root:
        count = len(root_checkpoints) // checkpoint_bytes
        if code_point < read_21(root_checkpoints, 0):
            return dfa_dead
        lower = 0
        upper = count
        while lower + 1 < upper:
            middle = lower + (upper - lower) // 2
            start = read_21(root_checkpoints, middle * checkpoint_bytes)
            if start <= code_point:
                lower = middle
            else:
                upper = middle
        checkpoint = lower * checkpoint_bytes
        known_start = read_21(root_checkpoints, checkpoint)
        offset = read_16(
            root_checkpoints,
            checkpoint + encoded_u21_bytes,
        )
    else:
        offset = dfa_offset(states, state)

    previous = -1
    first = True
    while offset < end:
        gap, offset = decode_uleb(transitions, offset)
        span, offset = decode_uleb(transitions, offset)
        target = transitions[offset]
        offset += 1
        if first and known_start is not None:
            start = known_start
        else:
            start = previous + 1 + gap
        first = False
        stop = start + span
        if code_point < start:
            return dfa_dead
        if code_point <= stop:
            return target
        previous = stop
    return dfa_dead


def decode_dfa_sequences(states, transitions, root):
    decoded_sequences = {}

    def walk(state, prefix):
        action = dfa_action(states, state)
        if action != action_none:
            decoded_sequences[tuple(prefix)] = action
        for lower, upper, target in decode_dfa_ranges(
            states,
            transitions,
            state,
        ):
            for code_point in range(lower, upper + 1):
                walk(target, prefix + [code_point])

    walk(root, [])
    return decoded_sequences


# Each state entry holds a transition offset and the accepted action.
# Transitions store gap, span, and a one-byte target for sorted ranges. Root
# checkpoints index into the root state's transition list.
def encode_dfa(presentation_sequences):
    minimized, root = minimize_dfa(presentation_sequences)
    entries = []
    transitions = bytearray()
    root_checkpoints = bytearray()

    for state, (action, edges) in enumerate(minimized):
        if len(transitions) >= dfa_offset_limit:
            raise ValueError(
                "DFA transition offset no longer fits in "
                f"{dfa_offset_bits} bits"
            )
        entries.append(len(transitions) | (action << dfa_action_shift))
        previous = -1
        for index, (lower, upper, target) in enumerate(transition_ranges(edges)):
            if state == root and index % dfa_root_block == 0:
                append_21(root_checkpoints, lower)
                append_16(root_checkpoints, len(transitions))
            encode_uleb(lower - previous - 1, transitions)
            encode_uleb(upper - lower, transitions)
            transitions.append(target)
            previous = upper

    if len(transitions) >= dfa_offset_limit:
        raise ValueError(
            f"DFA transition stream no longer fits in {dfa_offset_bits} bits"
        )
    entries.append(len(transitions))
    states = bytearray()
    for entry in entries:
        append_16(states, entry)

    if decode_dfa_sequences(states, transitions, root) != presentation_sequences:
        raise ValueError("DFA encoding failed")
    return states, transitions, root_checkpoints, root


# Source rendering

def format_bytes(name, data):
    lines = [f"static const unsigned char {name}[] = {{"]
    for index in range(0, len(data), 16):
        chunk = data[index : index + 16]
        lines.append("    " + ", ".join(f"0x{value:02X}" for value in chunk) + ",")
    lines.append("};")
    return "\n".join(lines)


def render_source(tables):
    template = template_path.read_text(encoding="utf-8")
    body = template.split("/* BEGIN GENERATED SOURCE */", 1)[1].lstrip()
    replacements = {
        "@property_dictionary@": format_bytes(
            "uw_property_dictionary",
            tables["property_dictionary"],
        ),
        "@property_checkpoints@": format_bytes(
            "uw_property_checkpoints",
            tables["property_checkpoints"],
        ),
        "@property_stream@": format_bytes(
            "uw_property_stream",
            tables["property_stream"],
        ),
        "@property_pages@": format_bytes(
            "uw_property_pages",
            tables["property_pages"],
        ),
        "@dfa_states@": format_bytes("uw_dfa_states", tables["dfa_states"]),
        "@dfa_transitions@": format_bytes(
            "uw_dfa_transitions",
            tables["dfa_transitions"],
        ),
        "@dfa_root_checkpoints@": format_bytes(
            "uw_dfa_root_checkpoints",
            tables["dfa_root_checkpoints"],
        ),
        "@property_run_count@": str(tables["property_run_count"]),
        "@property_run_block@": str(property_run_block),
        "@property_dictionary_index_bits@": str(
            property_dictionary_index_bits
        ),
        "@property_page_shift@": str(property_page_shift),
        "@encoded_u16_bytes@": str(encoded_u16_bytes),
        "@encoded_u21_bytes@": str(encoded_u21_bytes),
        "@grapheme_break_mask@": f"0x{grapheme_break_mask:02X}",
        "@extended_pictographic_bit@": f"0x{extended_pictographic_bit:02X}",
        "@indic_conjunct_break_shift@": str(indic_conjunct_break_shift),
        "@indic_conjunct_break_mask@": f"0x{indic_conjunct_break_mask:02X}",
        "@contribution_shift@": str(contribution_shift),
        "@contribution_mask@": f"0x{contribution_mask:02X}",
        "@dfa_start_bit@": f"0x{dfa_start_bit:04X}",
        "@emoji_stage_mask@": f"0x{emoji_stage_mask:02X}",
        "@emoji_stage_none@": str(emoji_stage_none),
        "@emoji_stage_extended_pictographic@": str(
            emoji_stage_extended_pictographic
        ),
        "@emoji_stage_zwj@": str(emoji_stage_zwj),
        "@property_checkpoint_count@": str(
            len(tables["property_checkpoints"]) // checkpoint_bytes
        ),
        "@dfa_root@": str(tables["dfa_root"]),
        "@dfa_offset_bits@": str(dfa_offset_bits),
        "@ascii_limit@": f"0x{ascii_limit:02X}",
        "@ascii_printable_first@": f"0x{ascii_printable_first:02X}",
        "@ascii_printable_last@": f"0x{ascii_printable_last:02X}",
        "@cr_code_point@": f"0x{cr_code_point:02X}",
        "@lf_code_point@": f"0x{lf_code_point:02X}",
        "@dfa_dead@": str(dfa_dead),
        "@dfa_root_checkpoint_count@": str(
            len(tables["dfa_root_checkpoints"]) // checkpoint_bytes
        ),
        "@ascii_keycap_dfa_state@": str(tables["ascii_keycap_dfa_state"]),
    }
    for marker, value in replacements.items():
        body = body.replace(marker, value)
    if "@" in body:
        raise ValueError("unexpanded template marker")

    return (
        f"""/*
 * Generated from Unicode {unicode_version} data.
 *
 * Copyright 2025-2026 Dair Aidarkhanov
 * SPDX-License-Identifier: 0BSD AND Unicode-3.0
 */

"""
        + body
    )


# Full Unicode model

def load_unicode_model(source_paths):
    grapheme_break = load_grapheme_break_classes(
        source_paths["GraphemeBreakProperty.txt"]
    )
    default_ignorable, grapheme_extend, indic_conjunct_break = (
        load_derived_core_properties(source_paths["DerivedCoreProperties.txt"])
    )
    zero_width = bytearray(
        default_ignorable_value | grapheme_extend_value
        for default_ignorable_value, grapheme_extend_value in zip(
            default_ignorable,
            grapheme_extend,
        )
    )
    east_asian_width = load_east_asian_width(
        source_paths["DerivedEastAsianWidth.txt"]
    )
    controls, decompositions = load_unicode_data(source_paths["UnicodeData.txt"])
    extended_pictographic = load_extended_pictographic(
        source_paths["emoji-data.txt"]
    )
    width_contributions = derive_width_contributions(
        east_asian_width,
        zero_width,
        decompositions,
    )
    presentation_sequences = load_presentation_sequences(
        source_paths,
        decompositions,
    )
    presentation_sequence_starters = {
        sequence[0] for sequence in presentation_sequences
    }
    return {
        "grapheme_break": grapheme_break,
        "extended_pictographic": extended_pictographic,
        "indic_conjunct_break": indic_conjunct_break,
        "controls": controls,
        "width_contributions": width_contributions,
        "presentation_sequence_starters": presentation_sequence_starters,
        "presentation_sequences": presentation_sequences,
    }


# Generation

def build_tables(source_paths):
    unicode_model = load_unicode_model(source_paths)
    dictionary, checkpoints, stream, pages, run_count = encode_property_table(
        unicode_model["grapheme_break"],
        unicode_model["extended_pictographic"],
        unicode_model["indic_conjunct_break"],
        unicode_model["controls"],
        unicode_model["width_contributions"],
        unicode_model["presentation_sequence_starters"],
    )
    states, transitions, root_checkpoints, root = encode_dfa(
        unicode_model["presentation_sequences"]
    )
    ascii_keycap_state = find_ascii_keycap_dfa_state(
        states,
        transitions,
        root,
        root_checkpoints,
    )
    return {
        "property_dictionary": dictionary,
        "property_checkpoints": checkpoints,
        "property_stream": stream,
        "property_pages": pages,
        "property_run_count": run_count,
        "dfa_states": states,
        "dfa_transitions": transitions,
        "dfa_root_checkpoints": root_checkpoints,
        "dfa_root": root,
        "ascii_keycap_dfa_state": ascii_keycap_state,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=unicode_data_directory,
    )
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    source_paths = load_unicode_sources(arguments.data_dir.resolve())
    tables = build_tables(source_paths)
    source = render_source(tables)
    if arguments.check:
        if output_path.read_text(encoding="utf-8") != source:
            raise ValueError(f"{output_path.name} is stale")
    else:
        with output_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(source)
        print(f"wrote {output_path.name}")


if __name__ == "__main__":
    main()
