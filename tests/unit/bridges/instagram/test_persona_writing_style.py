"""Persona Analysis — owner writing-style line extraction (pure, no device).

`owner_lines_from_comment_descs` keeps only the comment rows authored by the analyzed account
(its own voice), stripping the leading author handle from the row content-desc. This is the pure
core of the writing-style enrichment folded into persona analysis; on-device row reading + reply
expansion are validated separately on real dumps.
"""

from bridges.instagram.analysis.runtime.persona_comments import (
    owner_lines_from_comment_descs,
)


def test_keeps_only_owner_rows_and_strips_handle():
    pairs = [
        ("someone great post!", "someone"),
        ("prospect merci beaucoup 😊", "prospect"),
        ("fan love it", "fan"),
        ("prospect trop gentil !", "prospect"),
    ]
    lines = owner_lines_from_comment_descs(pairs, "@Prospect")
    assert lines == ["merci beaucoup 😊", "trop gentil !"]


def test_dedup_and_length_bounds():
    pairs = [
        ("me hello", "me"),
        ("me hello", "me"),          # duplicate
        ("me ok", "me"),             # text too short (<3 after strip)
        ("me " + "x" * 300, "me"),   # too long
        ("me a real sentence here", "me"),
    ]
    lines = owner_lines_from_comment_descs(pairs, "me")
    assert lines == ["hello", "a real sentence here"]


def test_cross_post_dedup_via_shared_seen():
    seen: set = set()
    a = owner_lines_from_comment_descs([("me same line", "me")], "me", seen=seen)
    b = owner_lines_from_comment_descs([("me same line", "me")], "me", seen=seen)
    assert a == ["same line"]
    assert b == []


def test_only_strips_leading_author_occurrence():
    # The handle may legitimately reappear inside the text; strip only the leading author token.
    pairs = [("me tag me in the next one", "me")]
    lines = owner_lines_from_comment_descs(pairs, "me")
    assert lines == ["tag me in the next one"]


def test_empty_when_no_owner_or_no_match():
    assert owner_lines_from_comment_descs([("x hi there", "x")], "") == []
    assert owner_lines_from_comment_descs([], "me") == []
    assert owner_lines_from_comment_descs([("x hello", "x")], "me") == []
