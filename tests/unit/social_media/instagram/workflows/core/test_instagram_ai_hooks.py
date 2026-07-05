from taktik.core.social_media.instagram.ui.selectors.surfaces.post import (
    POST_DETAIL_SELECTORS,
)
import pytest

from taktik.core.shared.text import detect_text_language
from taktik.core.social_media.instagram.workflows.core.ai_hooks import (
    crop_screenshot_to_post,
    install_instagram_ai_hooks,
    _load_cached_qualification,
    _resolve_comment_language,
)


class FakeElement:
    def __init__(self, exists, bounds=None):
        self.exists = exists
        self.info = {"bounds": bounds or {}}


class FakeDevice:
    def __init__(self, elements):
        self.elements = elements

    def xpath(self, selector):
        return self.elements.get(selector, FakeElement(False))


class FakeImage:
    size = (100, 200)

    def __init__(self):
        self.crop_box = None

    def crop(self, box):
        cropped = FakeImage()
        cropped.crop_box = box
        return cropped


def test_crop_screenshot_to_post_uses_post_selector_catalogs():
    image = FakeImage()
    device = FakeDevice(
        {
            POST_DETAIL_SELECTORS.ai_crop_header_selectors[0]: FakeElement(
                True,
                {"top": 40},
            ),
            POST_DETAIL_SELECTORS.ai_crop_button_row_selectors[0]: FakeElement(
                True,
                {"bottom": 150},
            ),
        }
    )

    cropped = crop_screenshot_to_post(image, device)

    assert cropped.crop_box == (0, 32, 100, 156)


def test_install_ai_hooks_without_device_is_noop_and_logs_warning():
    logs = []

    install_instagram_ai_hooks(
        ai=object(),
        ai_config={"smartComments": True},
        device=None,
        log=lambda level, message: logs.append((level, message)),
    )

    assert logs == [("warning", "AI hooks: no device available, skipping")]


@pytest.mark.parametrize(
    "base_lang, post_language, expected",
    [
        # base_lang = account preferred language (fallback app). Allowed = {base_lang, English}.
        ("fr", "French", "fr"),           # post in base language -> comment in it
        ("fr", "english", "en"),          # English always allowed (case-insensitive)
        ("fr", "Spanish", None),          # other language -> skip
        ("fr", "Chinese", None),
        ("fr", None, "fr"),               # undetected -> default to base language
        ("fr", "", "fr"),
        ("en", "English", "en"),
        ("en", "French", None),           # EN account: French is NOT allowed (only English)
        ("en", None, "en"),
        ("en", "Mandarin", None),
        # Account targeting a non-FR/EN audience (preferred_language beyond fr/en).
        ("es", "Spanish", "es"),
        ("es", "español", "es"),
        ("es", "Castellano", "es"),
        ("es", "English", "en"),          # English still allowed for a Spanish account
        ("es", "French", None),           # Spanish account, French post -> skip
        ("es", None, "es"),
        ("de", "German", "de"),
        ("ar", "Arabic", "ar"),
        ("it", "Italian", "it"),
        ("pt", "Portuguese", "pt"),
        # Robustness: a name that merely CONTAINS "en" must not be read as English.
        ("fr", "Slovenian", None),
        # The model may emit a code instead of a name.
        ("fr", "fr", "fr"),
        ("fr", "en", "en"),
        # Decorated name (flag/extra) still resolves via startswith.
        ("fr", "French (Français)", "fr"),
    ],
)
def test_resolve_comment_language_policy(base_lang, post_language, expected):
    assert _resolve_comment_language(base_lang, post_language) == expected


@pytest.mark.parametrize(
    "base_lang, caption, expected",
    [
        # The account language is the ANCHOR; the CAPTION decides the comment language, never the
        # vision guess. This is the effective policy the smart-comment hook applies.
        # French account, French caption -> French (the erika.spahn regression).
        ("fr", "Venez voir, revoir ou découvrir les IMPROMPTU pour deux concepts d'improvisa… more", "fr"),
        # French account, English caption -> English is allowed as the bilingual 2nd language.
        ("fr", "Omg this sounds so fun! love both concepts", "en"),
        # French account, caption too short/ambiguous -> DEFAULT to the account language (NOT English).
        ("fr", "🎉🎉", "fr"),
        ("fr", "", "fr"),
        ("fr", None, "fr"),
        # English account: English caption -> English; a French post -> skip (an English-only
        # account doesn't claim to speak French, so commenting in French isn't credible).
        ("en", "The new collection is finally here, check it out", "en"),
        ("en", "Venez nous voir pour deux concepts avec les amis", None),
    ],
)
def test_effective_comment_language_from_caption(base_lang, caption, expected):
    # Mirrors the hook: comment language = _resolve_comment_language(account_lang, caption_language).
    assert _resolve_comment_language(base_lang, detect_text_language(caption)) == expected


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def get_profiles_by_usernames(self, usernames):
        return list(self._rows)


def _patch_db(monkeypatch, rows):
    monkeypatch.setattr(
        "taktik.core.database.local.service.get_local_database",
        lambda: _FakeDb(rows),
    )


def test_load_cached_qualification_reuses_stored_niche(monkeypatch):
    # A profile already AI-qualified in the DB is returned so the interaction hook can reuse it
    # instead of re-paying for a fresh vision classification.
    _patch_db(monkeypatch, [{"username": "known", "niche": "fitness", "niche_category": "sport"}])
    row = _load_cached_qualification("known")
    assert row is not None
    assert row["niche"] == "fitness"


def test_load_cached_qualification_matches_case_insensitively(monkeypatch):
    _patch_db(monkeypatch, [{"username": "Known_User", "profession": "coach"}])
    assert _load_cached_qualification("known_user") is not None


def test_load_cached_qualification_none_when_not_ai_qualified(monkeypatch):
    # A bare profile row with no niche/category/profession must NOT be treated as qualified.
    _patch_db(monkeypatch, [{"username": "bare", "full_name": "Bare Profile"}])
    assert _load_cached_qualification("bare") is None


def test_load_cached_qualification_none_when_absent(monkeypatch):
    _patch_db(monkeypatch, [])
    assert _load_cached_qualification("ghost") is None


def test_load_cached_qualification_handles_db_errors(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("taktik.core.database.local.service.get_local_database", _boom)
    assert _load_cached_qualification("whoever") is None
