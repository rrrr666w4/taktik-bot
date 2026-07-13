"""The scraping bridge config mapper must forward the profile filters.

Device bug (2026-07-12): a profile with 0 posts was scraped, saved AND deep-qualified (paid AI)
even though the operator had set "Min posts = 1". The filter code itself was correct — it was
never fed: `build_scraping_config` is a WHITELIST mapper and simply did not copy any of the
filter keys, so the workflow read them from an empty config and every filter evaluated to
"disabled". No min followers, no min posts, no skip-private: NONE of the scraping filters had
ever worked.

Also locks the upper-bound rule: the UI happily leaves 0 in a "max" field (seen on a real run:
"Max followers: 0"), which every operator reads as "no maximum". Forwarding it literally would
reject every profile with a single follower and scrape nothing.
"""

import pytest

from bridges.instagram.scraping.runtime.config import build_scraping_config


def _cfg(**over):
    base = {'type': 'target', 'targetUsernames': ['someone']}
    base.update(over)
    return build_scraping_config(base)


def test_min_posts_reaches_the_workflow():
    """The exact regression: minPosts=1 must not be dropped."""
    assert _cfg(minPosts=1)['minPosts'] == 1


def test_every_filter_key_is_forwarded():
    cfg = _cfg(
        minFollowers=10, maxFollowers=50000,
        minFollowing=50, maxFollowing=7500,
        minPosts=3,
        requireProfilePicture=True, skipPrivateProfiles=False,
    )
    assert cfg['minFollowers'] == 10
    assert cfg['maxFollowers'] == 50000
    assert cfg['minFollowing'] == 50
    assert cfg['maxFollowing'] == 7500
    assert cfg['minPosts'] == 3
    assert cfg['requireProfilePicture'] is True
    assert cfg['skipPrivateProfiles'] is False


def test_absent_filter_stays_disabled():
    """The front sends null for an empty field — the key must not appear at all."""
    cfg = _cfg(minPosts=None, minFollowers=None)
    assert 'minPosts' not in cfg
    assert 'minFollowers' not in cfg


def test_zero_lower_bound_is_kept_literally():
    """0 is a meaningful lower bound (and harmless) — it must not be swallowed by a truthy test."""
    assert _cfg(minPosts=0)['minPosts'] == 0


def test_zero_upper_bound_means_no_limit_not_zero_followers():
    """The guard that prevents a far worse bug: 'Max followers: 0' must not scrape nothing."""
    cfg = _cfg(maxFollowers=0, maxFollowing=0)
    assert 'maxFollowers' not in cfg
    assert 'maxFollowing' not in cfg


def test_skip_private_defaults_to_true():
    assert _cfg()['skipPrivateProfiles'] is True
    assert _cfg()['requireProfilePicture'] is False


def test_filters_do_not_disturb_the_rest_of_the_config():
    cfg = _cfg(minPosts=1, maxProfiles=250, enrichProfiles=True, deepQualify=True)
    assert cfg['max_profiles'] == 250
    assert cfg['enrich_profiles'] is True
    assert cfg['deep_qualify'] is True
    assert cfg['type'] == 'target'
