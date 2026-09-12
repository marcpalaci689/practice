import string

import pytest

from url_shortener import (
    B62Encoder,
    InvalidUrlError,
    JsonFileStore,
    LongUrl,
    UnknownCodeError,
    URLShortener,
)

BASE62 = string.ascii_letters + string.digits
DEFAULT_BASE = "https://sho.rt/"


class CollisionEncoder:
    """Forces a collision when perturbation is None so shorten must retry."""

    COLLISION_CODE = "aaaaaaaa"
    RESOLVED_CODE = "bbbbbbbb"

    def __init__(self) -> None:
        self.perturbations: list[int | None] = []

    def encode(self, long_url: LongUrl, perturbation: int | None = None) -> str:
        self.perturbations.append(perturbation)
        if perturbation is None:
            return self.COLLISION_CODE
        return self.RESOLVED_CODE


class TestLongUrl:
    def test_accepts_http(self):
        assert LongUrl("http://example.com").url == "http://example.com"

    def test_accepts_https(self):
        assert LongUrl("https://example.com").url == "https://example.com"

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com",
            "example.com",
            "javascript:alert(1)",
            "",
            "https:/example.com",
        ],
    )
    def test_rejects_invalid_scheme(self, url: str):
        with pytest.raises(InvalidUrlError):
            LongUrl(url)


class TestB62Encoder:
    def setup_method(self):
        self.encoder = B62Encoder()

    def test_encode_is_deterministic(self):
        url = LongUrl("https://example.com/path")
        assert self.encoder.encode(url) == self.encoder.encode(url)
        assert self.encoder.encode(url, None) == self.encoder.encode(url, None)

    def test_encode_same_url_same_perturbation_is_stable(self):
        url = LongUrl("https://example.com")
        assert self.encoder.encode(url, 3) == self.encoder.encode(url, 3)

    def test_none_differs_from_integer_perturbation(self):
        url = LongUrl("https://example.com")
        assert self.encoder.encode(url, None) != self.encoder.encode(url, 0)

    def test_different_perturbation_seeds_produce_different_codes(self):
        url = LongUrl("https://example.com")
        assert self.encoder.encode(url, 0) != self.encoder.encode(url, 1)

    def test_different_urls_produce_different_codes(self):
        a = LongUrl("https://example.com/a")
        b = LongUrl("https://example.com/b")
        assert self.encoder.encode(a) != self.encoder.encode(b)

    def test_code_is_exactly_eight_base62_chars(self):
        code = self.encoder.encode(LongUrl("https://example.com"))
        assert len(code) == 8
        assert all(ch in BASE62 for ch in code)

    def test_perturbed_url_is_deterministic_shuffle_of_original(self):
        url = "https://example.com"
        first = self.encoder._perturbed_url(url, 7)
        second = self.encoder._perturbed_url(url, 7)
        assert first == second
        assert first != url
        assert sorted(first) == sorted(url)


class TestURLShortener:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.shortener = URLShortener(store=JsonFileStore(tmp_path / "short_urls.json"))
        self.long_url = LongUrl("https://example.com/page")

    def test_shorten_uses_base_url_and_eight_char_code(self):
        short_url = self.shortener.shorten(self.long_url)
        assert short_url.startswith(DEFAULT_BASE)
        code = short_url.removeprefix(DEFAULT_BASE)
        assert len(code) == 8
        assert all(ch in BASE62 for ch in code)

    def test_shorten_same_url_is_idempotent(self):
        first = self.shortener.shorten(self.long_url)
        second = self.shortener.shorten(LongUrl("https://example.com/page"))
        assert first == second

    def test_different_urls_get_different_short_urls(self):
        a = self.shortener.shorten(LongUrl("https://example.com/a"))
        b = self.shortener.shorten(LongUrl("https://example.com/b"))
        assert a != b

    def test_resolve_shorten_round_trip(self):
        short_url = self.shortener.shorten(self.long_url)
        assert self.shortener.resolve(short_url) == self.long_url

    def test_unknown_well_formed_short_url_raises(self):
        with pytest.raises(UnknownCodeError):
            self.shortener.resolve(f"{DEFAULT_BASE}xxxxxxxx")

    @pytest.mark.parametrize(
        "short_url",
        [
            "https://evil.example/aaaaaaaa",
            "aaaaaaaa",
            f"{DEFAULT_BASE}short",
            f"{DEFAULT_BASE}toolong12",
            f"{DEFAULT_BASE}aaaaaaa!",
        ],
    )
    def test_malformed_short_url_raises_invalid(self, short_url: str):
        with pytest.raises(InvalidUrlError):
            self.shortener.resolve(short_url)

    def test_custom_base_url_is_used_for_shorten_and_resolve(self, tmp_path):
        shortener = URLShortener(
            base_url="https://tiny.test/",
            store=JsonFileStore(tmp_path / "custom.json"),
        )
        long_url = LongUrl("https://example.com/custom")
        short_url = shortener.shorten(long_url)

        assert short_url.startswith("https://tiny.test/")
        assert shortener.resolve(short_url) == long_url
        with pytest.raises(InvalidUrlError):
            shortener.resolve(f"{DEFAULT_BASE}{short_url.removeprefix('https://tiny.test/')}")


class TestCollisions:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.encoder = CollisionEncoder()
        self.shortener = URLShortener(
            encoder=self.encoder,
            store=JsonFileStore(tmp_path / "short_urls.json"),
        )
        self.url_a = LongUrl("https://example.com/a")
        self.url_b = LongUrl("https://example.com/b")

    def test_second_url_is_retried_with_integer_perturbation(self):
        short_a = self.shortener.shorten(self.url_a)
        short_b = self.shortener.shorten(self.url_b)

        assert short_a == f"{DEFAULT_BASE}{CollisionEncoder.COLLISION_CODE}"
        assert short_b == f"{DEFAULT_BASE}{CollisionEncoder.RESOLVED_CODE}"
        assert short_a != short_b
        assert self.encoder.perturbations == [None, None, 0]

    def test_resolve_returns_original_urls_after_collision(self):
        short_a = self.shortener.shorten(self.url_a)
        short_b = self.shortener.shorten(self.url_b)

        assert self.shortener.resolve(short_a) == self.url_a
        assert self.shortener.resolve(short_b) == self.url_b

    def test_first_url_stays_idempotent_after_later_collision(self):
        short_a = self.shortener.shorten(self.url_a)
        self.shortener.shorten(self.url_b)
        assert self.shortener.shorten(LongUrl("https://example.com/a")) == short_a


class RecordingStore:
    """In-memory store that records save() calls."""

    def __init__(self) -> None:
        self.saves: list[dict[str, str]] = []
        self._data: dict[str, str] = {}

    def load(self) -> dict[str, str]:
        return dict(self._data)

    def save(self, data: dict[str, str]) -> None:
        self.saves.append(dict(data))
        self._data = dict(data)


class TestJsonFileStore:
    def test_missing_file_loads_empty(self, tmp_path):
        store = JsonFileStore(tmp_path / "short_urls.json")
        assert store.load() == {}

    def test_save_then_load_round_trips(self, tmp_path):
        store = JsonFileStore(tmp_path / "short_urls.json")
        store.save({"https://example.com/a": "aaaaaaaa"})
        assert store.load() == {"https://example.com/a": "aaaaaaaa"}

    def test_second_store_instance_sees_first_writes(self, tmp_path):
        path = tmp_path / "short_urls.json"
        first = JsonFileStore(path)
        first.save({"https://example.com/a": "aaaaaaaa"})
        second = JsonFileStore(path)
        assert second.load() == {"https://example.com/a": "aaaaaaaa"}


class TestPersistence:
    def test_new_code_calls_save_once(self):
        store = RecordingStore()
        shortener = URLShortener(store=store)
        long_url = LongUrl("https://example.com/page")
        short_url = shortener.shorten(long_url)
        code = short_url.removeprefix(DEFAULT_BASE)
        assert store.saves == [{long_url.url: code}]

    def test_cache_hit_does_not_call_save(self):
        store = RecordingStore()
        shortener = URLShortener(store=store)
        long_url = LongUrl("https://example.com/page")
        shortener.shorten(long_url)
        shortener.shorten(LongUrl("https://example.com/page"))
        assert len(store.saves) == 1

    def test_restart_resolve_remembers_previous_short_url(self, tmp_path):
        path = tmp_path / "short_urls.json"
        long_url = LongUrl("https://example.com/remembered")
        shortener = URLShortener(store=JsonFileStore(path))
        short_url = shortener.shorten(long_url)
        del shortener

        restarted = URLShortener(store=JsonFileStore(path))
        assert restarted.resolve(short_url) == long_url

    def test_restart_shorten_is_idempotent(self, tmp_path):
        path = tmp_path / "short_urls.json"
        long_url = LongUrl("https://example.com/remembered")
        shortener = URLShortener(
            store=JsonFileStore(path),
            encoder=CollisionEncoder(),
        )
        short_url = shortener.shorten(long_url)
        assert short_url == f"{DEFAULT_BASE}{CollisionEncoder.COLLISION_CODE}"
        del shortener

        restarted = URLShortener(store=JsonFileStore(path))
        assert restarted.shorten(long_url) == short_url

    def test_restart_keeps_old_mapping_when_shortening_a_new_url(self, tmp_path):
        path = tmp_path / "short_urls.json"
        old_url = LongUrl("https://example.com/old")
        new_url = LongUrl("https://example.com/new")
        shortener = URLShortener(store=JsonFileStore(path))
        old_short = shortener.shorten(old_url)
        del shortener

        restarted = URLShortener(store=JsonFileStore(path))
        new_short = restarted.shorten(new_url)
        assert new_short != old_short
        assert restarted.resolve(old_short) == old_url
        assert restarted.resolve(new_short) == new_url

    def test_restart_does_not_invent_unpersisted_mappings(self, tmp_path):
        path = tmp_path / "short_urls.json"
        restarted = URLShortener(store=JsonFileStore(path))
        with pytest.raises(UnknownCodeError):
            restarted.resolve(f"{DEFAULT_BASE}xxxxxxxx")

