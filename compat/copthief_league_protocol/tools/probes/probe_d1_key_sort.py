"""PROBE D1 — canonical JSON's key ORDER diverges across languages, unexercised by any vector.

Finding (anrbj666 audit, 2026-08-04): `sort_keys=True` sorts by Unicode CODE POINT in Python,
but JavaScript's `Object.keys().sort()`, Java's `String.compareTo` and C#'s ordinal compare sort
by UTF-16 CODE UNIT. The two orders disagree whenever an ASTRAL key (U+10000 and above, encoded
as a surrogate pair whose leading unit is 0xD800-0xDBFF) meets a key in the high BMP range
(U+E000 and above). Every published fixture has ASCII keys or Hebrew keys — Hebrew is BMP
(U+0590 block), where all orders coincide — and canonical_json.json puts non-ASCII only in
VALUES. So a JS/Java/C# implementation can pass every vector and still produce a different
canonical string, which is a different commit, which reads as tampering to both honest peers.

Run:  python probe_d1_key_sort.py
Stdlib only; does not import the kit (the divergence is in the serializers, not the kit).
"""

import json

# U+FF5E FULLWIDTH TILDE: BMP, one UTF-16 code unit, 0xFF5E
# U+1F642 SLIGHTLY SMILING FACE: astral, surrogate pair, leading unit 0xD83D
BMP_KEY, ASTRAL_KEY = "～", "\U0001f642"


def utf16_units(text: str) -> list[int]:
    """The UTF-16 code units a JS/Java/C# string comparison actually sorts on."""
    return [int.from_bytes(text.encode("utf-16-be")[i:i + 2], "big")
            for i in range(0, len(text.encode("utf-16-be")), 2)]


def main() -> int:
    payload = {ASTRAL_KEY: 1, BMP_KEY: 2}

    python_order = list(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":")))
    python_first = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"))
    # What a UTF-16-code-unit sort produces (JS/Java/C#):
    utf16_sorted = sorted(payload, key=utf16_units)
    utf16_first = json.dumps({k: payload[k] for k in utf16_sorted},
                             sort_keys=False, ensure_ascii=False, separators=(",", ":"))

    print(f"  keys: BMP U+FF5E {BMP_KEY!r} (units {utf16_units(BMP_KEY)}) | "
          f"astral U+1F642 {ASTRAL_KEY!r} (units {utf16_units(ASTRAL_KEY)})")
    print(f"  code-point sort  (Python sort_keys): {python_first}")
    print(f"  code-unit  sort  (JS/Java/C#):       {utf16_first}")
    diverges = python_first != utf16_first
    print()
    print(f"  canonical strings differ: {diverges}  -> different SHA-256 -> "
          f"audit reads TAMPERING between two honest peers")
    print()
    print("VERDICT: " + ("REPRODUCED — one fixture with these two keys closes it"
                         if diverges else "no divergence (unexpected)"))
    del python_order
    return 0 if diverges else 1


if __name__ == "__main__":
    raise SystemExit(main())
