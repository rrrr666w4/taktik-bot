"""Anti-regression: bot-side session finalization must persist the stats snapshot.

Bug found on real data (2026-07): sessions the bot ended itself (COMPLETED) carried
stats_total_interactions=0 and end_time NULL even though the interactions table held
100+ real rows for them — only Electron's manual-stop path wrote the snapshot, so the
client dashboard under-reported the account's work by ~4x. finalize() must aggregate
interactions with the exact same semantics as Electron's resolveSessionStats.
"""

from taktik.core.database.repositories.instagram.session.session_repository import SessionRepository


def _create_session(conn) -> int:
    conn.execute(
        "INSERT INTO accounts (platform, legacy_account_id, username, is_bot) VALUES ('instagram', 1, 'bot', 1)"
    )
    repo = SessionRepository(conn)
    session_id = repo.create(
        account_id=1, session_name='test_session', target_type='USER', target='someone'
    )
    assert session_id is not None
    return session_id


def _insert_interaction(conn, session_id: int, interaction_type: str, count: int = 1):
    for _ in range(count):
        conn.execute(
            """INSERT INTO interactions
               (platform, session_id, account_id, profile_id, interaction_type, success, interaction_time, created_at)
               VALUES ('instagram', ?, 1, 10, ?, 1, datetime('now'), datetime('now'))""",
            (session_id, interaction_type),
        )


def test_finalize_writes_end_time_and_stats_snapshot(conn):
    session_id = _create_session(conn)
    _insert_interaction(conn, session_id, 'LIKE', 5)
    _insert_interaction(conn, session_id, 'FOLLOW', 2)
    _insert_interaction(conn, session_id, 'COMMENT', 1)
    _insert_interaction(conn, session_id, 'STORY_WATCH', 3)
    _insert_interaction(conn, session_id, 'STORY_LIKE', 1)
    _insert_interaction(conn, session_id, 'PROFILE_VISIT', 4)
    _insert_interaction(conn, session_id, 'UNFOLLOW', 1)
    conn.commit()

    repo = SessionRepository(conn)
    assert repo.finalize(session_id, 'COMPLETED', duration_seconds=1234) is True

    row = conn.execute(
        """SELECT status, end_time, duration_seconds, stats_total_interactions, stats_likes,
                  stats_follows, stats_unfollows, stats_comments, stats_story_views,
                  stats_story_likes, stats_profile_visits
           FROM sessions_unified WHERE platform='instagram' AND legacy_session_id=?""",
        (session_id,),
    ).fetchone()

    assert row['status'] == 'COMPLETED'
    assert row['end_time'] is not None
    assert row['duration_seconds'] == 1234
    assert row['stats_likes'] == 5
    assert row['stats_follows'] == 2
    assert row['stats_comments'] == 1
    assert row['stats_story_views'] == 3
    assert row['stats_story_likes'] == 1
    assert row['stats_profile_visits'] == 4
    assert row['stats_unfollows'] == 1
    # Electron's resolveSessionStats total: likes+follows+comments+story_views+story_likes,
    # unfollows and profile visits excluded.
    assert row['stats_total_interactions'] == 5 + 2 + 1 + 3 + 1


def test_finalize_with_no_interactions_zeroes_stats_and_sets_end_time(conn):
    session_id = _create_session(conn)
    conn.commit()

    repo = SessionRepository(conn)
    assert repo.finalize(session_id, 'INTERRUPTED') is True

    row = conn.execute(
        """SELECT status, end_time, stats_total_interactions
           FROM sessions_unified WHERE platform='instagram' AND legacy_session_id=?""",
        (session_id,),
    ).fetchone()
    assert row['status'] == 'INTERRUPTED'
    assert row['end_time'] is not None
    assert row['stats_total_interactions'] == 0


def test_finalize_only_counts_the_target_session(conn):
    first = _create_session(conn)
    repo = SessionRepository(conn)
    second = repo.create(account_id=1, session_name='other', target_type='USER', target='else')
    _insert_interaction(conn, first, 'LIKE', 3)
    _insert_interaction(conn, second, 'LIKE', 7)
    conn.commit()

    assert repo.finalize(first, 'COMPLETED') is True

    row = conn.execute(
        "SELECT stats_likes FROM sessions_unified WHERE platform='instagram' AND legacy_session_id=?",
        (first,),
    ).fetchone()
    assert row['stats_likes'] == 3


def test_service_finalize_session_records_daily_completion(db):
    account_id, _created = db.get_or_create_account(username='bot', is_bot=True)
    session_id = db.create_session(
        account_id=account_id, session_name='svc_session', target_type='USER', target='someone'
    )
    assert db.finalize_session(session_id, 'COMPLETED', duration_seconds=60) is True

    session = db.get_session(session_id)
    assert session['status'] == 'COMPLETED'
    assert session['end_time'] is not None
