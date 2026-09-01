"""Tests for the schema invariants.

Covers: slug uniqueness, ref-set version uniqueness per character,
exactly-one-canonical, canonical immutability (with canonical->retired
transition), FK integrity, integer-money storage, generation state values,
and multi-character cast_json.
"""

from __future__ import annotations

import json

import pytest
import sqlite3


def _insert_character(conn, slug="elias", name="Elias"):
    cur = conn.execute(
        "INSERT INTO character (name, slug) VALUES (?, ?)", (name, slug)
    )
    return cur.lastrowid


def _insert_ref_set(conn, character_id, version=1, status="draft"):
    cur = conn.execute(
        "INSERT INTO ref_set (character_id, version, status) VALUES (?, ?, ?)",
        (character_id, version, status),
    )
    return cur.lastrowid


def _insert_style(conn, name="victorian"):
    cur = conn.execute(
        "INSERT INTO style (name) VALUES (?)", (name,)
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# character slug uniqueness
# ---------------------------------------------------------------------------

def test_character_slug_unique(conn):
    _insert_character(conn, slug="elias")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_character(conn, slug="elias")


# ---------------------------------------------------------------------------
# ref_set version uniqueness per character
# ---------------------------------------------------------------------------

def test_ref_set_version_unique_per_character(conn):
    cid = _insert_character(conn)
    _insert_ref_set(conn, cid, version=1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_ref_set(conn, cid, version=1)


def test_same_version_allowed_for_different_characters(conn):
    c1 = _insert_character(conn, slug="elias")
    c2 = _insert_character(conn, slug="margaret")
    _insert_ref_set(conn, c1, version=1)
    # Same version for a different character is fine.
    _insert_ref_set(conn, c2, version=1)


# ---------------------------------------------------------------------------
# exactly one canonical ref_set per character
# ---------------------------------------------------------------------------

def test_exactly_one_canonical_per_character(conn):
    cid = _insert_character(conn)
    _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_ref_set(conn, cid, version=2, status="canonical")


def test_can_have_draft_alongside_canonical(conn):
    cid = _insert_character(conn)
    _insert_ref_set(conn, cid, version=1, status="canonical")
    # A draft alongside the canonical is allowed.
    _insert_ref_set(conn, cid, version=2, status="draft")


# ---------------------------------------------------------------------------
# canonical immutability (with canonical->retired transition allowed)
# ---------------------------------------------------------------------------

def test_draft_to_canonical_works(conn):
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="draft")
    conn.execute(
        "UPDATE ref_set SET status='canonical' WHERE id=?", (rsid,)
    )
    conn.commit()
    row = conn.execute("SELECT status FROM ref_set WHERE id=?", (rsid,)).fetchone()
    assert row["status"] == "canonical"


def test_canonical_to_retired_works(conn):
    """Promoting a new canonical set retires the prior one (Milestone 5)."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    conn.execute(
        "UPDATE ref_set SET status='retired' WHERE id=?", (rsid,)
    )
    conn.commit()
    row = conn.execute("SELECT status FROM ref_set WHERE id=?", (rsid,)).fetchone()
    assert row["status"] == "retired"


def test_canonical_other_field_update_blocked(conn):
    """Any update to a canonical row other than status->retired is blocked."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ref_set SET version=99 WHERE id=?", (rsid,)
        )


def test_canonical_status_change_to_non_retired_blocked(conn):
    """Changing a canonical row's status to anything other than 'retired' is blocked."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ref_set SET status='draft' WHERE id=?", (rsid,)
        )


def test_canonical_retired_with_other_change_blocked(conn):
    """Setting status to retired while also changing another field is blocked."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ref_set SET status='retired', version=99 WHERE id=?", (rsid,)
        )


def test_canonical_retired_with_created_at_change_blocked(conn):
    """Setting status to retired while also changing created_at is blocked."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ref_set SET status='retired', created_at='2020-01-01 00:00:00' "
            "WHERE id=?",
            (rsid,),
        )


def test_canonical_retired_with_id_change_blocked(conn):
    """Setting status to retired while also changing id is blocked."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ref_set SET status='retired', id=999 WHERE id=?", (rsid,)
        )


def test_canonical_ref_set_cannot_be_deleted(conn):
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ref_set WHERE id=?", (rsid,))


def test_images_in_canonical_ref_set_are_immutable(conn):
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, status="draft")
    image_id = conn.execute(
        "INSERT INTO ref_image (ref_set_id, sha256, role) VALUES (?, 'abc', 'face_front')",
        (rsid,),
    ).lastrowid
    conn.execute("UPDATE ref_set SET status = 'canonical' WHERE id = ?", (rsid,))
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE ref_image SET role = 'outfit' WHERE id = ?", (image_id,))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ref_image WHERE id = ?", (image_id,))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ref_image (ref_set_id, sha256, role) VALUES (?, 'def', 'outfit')",
            (rsid,),
        )


def test_images_in_retired_ref_set_remain_immutable(conn):
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, status="draft")
    image_id = conn.execute(
        "INSERT INTO ref_image (ref_set_id, sha256, role) VALUES (?, 'abc', 'face_front')",
        (rsid,),
    ).lastrowid
    conn.execute("UPDATE ref_set SET status = 'canonical' WHERE id = ?", (rsid,))
    conn.execute("UPDATE ref_set SET status = 'retired' WHERE id = ?", (rsid,))
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ref_image WHERE id = ?", (image_id,))


def test_retired_ref_set_can_be_deleted(conn):
    """Once retired, a ref_set is no longer canonical and can be deleted."""
    cid = _insert_character(conn)
    rsid = _insert_ref_set(conn, cid, version=1, status="canonical")
    conn.execute(
        "UPDATE ref_set SET status='retired' WHERE id=?", (rsid,)
    )
    conn.commit()
    conn.execute("DELETE FROM ref_set WHERE id=?", (rsid,))
    conn.commit()
    row = conn.execute("SELECT COUNT(*) AS n FROM ref_set WHERE id=?", (rsid,)).fetchone()
    assert row["n"] == 0


def test_canonical_promotion_retires_prior(conn):
    """Full Milestone 5 flow: promote v2, prior v1 becomes retired."""
    cid = _insert_character(conn)
    v1 = _insert_ref_set(conn, cid, version=1, status="canonical")
    v2 = _insert_ref_set(conn, cid, version=2, status="draft")

    # Promote v2 to canonical (retires v1 in the same transaction).
    conn.execute(
        "UPDATE ref_set SET status='retired' WHERE id=?", (v1,)
    )
    conn.execute(
        "UPDATE ref_set SET status='canonical' WHERE id=?", (v2,)
    )
    conn.commit()

    rows = {
        r["id"]: r["status"]
        for r in conn.execute("SELECT id, status FROM ref_set").fetchall()
    }
    assert rows[v1] == "retired"
    assert rows[v2] == "canonical"


# ---------------------------------------------------------------------------
# foreign-key integrity
# ---------------------------------------------------------------------------

def test_fk_enforced_on_ref_set(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ref_set (character_id, version) VALUES (99999, 1)"
        )


def test_fk_enforced_on_ref_image(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ref_image (ref_set_id, sha256, role) VALUES (99999, 'abc', 'face_front')"
        )


def test_fk_enforced_on_candidate(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO candidate (generation_id, sha256) VALUES (99999, 'abc')"
        )


def test_fk_enforced_on_character_default_style(conn):
    """character.default_style_id -> style(id) FK is enforced."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO character (name, slug, default_style_id) VALUES ('x', 'x', 99999)"
        )


def test_fk_enforced_on_generation_scene(conn):
    """generation.scene_id -> scene(id) FK is enforced."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO generation (scene_id, model) VALUES (99999, 'm')"
        )


def test_fk_enforced_on_generation_parent(conn):
    """generation.parent_generation_id -> generation(id) FK is enforced.

    A valid scene is inserted first so scene_id points to a real row; the ONLY
    dangling reference is parent_generation_id. This isolates the parent FK as
    the sole cause of the IntegrityError.
    """
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO generation (scene_id, model, parent_generation_id) VALUES (1, 'm', 99999)"
        )


def test_fk_valid_character_default_style(conn):
    """A valid default_style_id reference is accepted."""
    sid = _insert_style(conn)
    conn.execute(
        "INSERT INTO character (name, slug, default_style_id) VALUES ('x', 'x', ?)",
        (sid,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# monetary values stored as INTEGER minor units
# ---------------------------------------------------------------------------

def test_cost_stored_as_integer_cents(conn):
    cid = _insert_character(conn)
    conn.execute(
        "INSERT INTO scene (id) VALUES (1)"
    )
    conn.execute(
        "INSERT INTO generation (scene_id, model, cost_usd_cents) VALUES (1, 'm', 700)"
    )
    conn.commit()
    row = conn.execute(
        "SELECT cost_usd_cents, typeof(cost_usd_cents) AS t FROM generation"
    ).fetchone()
    assert row["cost_usd_cents"] == 700
    assert row["t"] == "integer"


def test_cost_column_rejects_float(conn):
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO generation (scene_id, model, cost_usd_cents) VALUES (1, 'm', 7.5)"
        )


# ---------------------------------------------------------------------------
# generation state values
# ---------------------------------------------------------------------------

def test_generation_state_defaults_to_pending(conn):
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    conn.execute("INSERT INTO generation (scene_id, model) VALUES (1, 'm')")
    conn.commit()
    row = conn.execute("SELECT state FROM generation").fetchone()
    assert row["state"] == "pending"


def test_generation_state_allows_valid_values(conn):
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    for state in ("pending", "succeeded", "failed"):
        conn.execute(
            "INSERT INTO generation (scene_id, model, state) VALUES (1, 'm', ?)",
            (state,),
        )
    conn.commit()


def test_generation_state_rejects_invalid(conn):
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO generation (scene_id, model, state) VALUES (1, 'm', 'running')"
        )


# ---------------------------------------------------------------------------
# multi-character cast_json
# ---------------------------------------------------------------------------

def test_cast_json_default_is_empty_list(conn):
    conn.execute("INSERT INTO scene (id) VALUES (1)")
    conn.commit()
    row = conn.execute("SELECT cast_json FROM scene WHERE id=1").fetchone()
    assert row["cast_json"] == "[]"


def test_cast_json_round_trips_ordered_list(conn):
    """An ordered list of N characters round-trips in order and completely."""
    cast = [
        {"character_id": 1, "role": "lead", "prominence": "primary"},
        {"character_id": 2, "role": "support", "prominence": "secondary"},
        {"character_id": 3, "role": "cameo", "prominence": "tertiary"},
    ]
    cast_json = json.dumps(cast)
    conn.execute(
        "INSERT INTO scene (id, cast_json) VALUES (1, ?)", (cast_json,)
    )
    conn.commit()

    row = conn.execute("SELECT cast_json FROM scene WHERE id=1").fetchone()
    round_tripped = json.loads(row["cast_json"])

    # Order preserved.
    assert [c["character_id"] for c in round_tripped] == [1, 2, 3]
    # Completeness preserved.
    assert round_tripped == cast
