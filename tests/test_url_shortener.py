import string

import pytest

from url_shortener import (
    B62Encoder,
    InvalidUrlError,
    LongUrl,
    UnknownCodeError,
    URLShortener,
)

BASE62 = string.ascii_letters + string.digits
DEFAULT_BASE = "https://sho.rt/"


class CollisionEncoder:
    """Forces a collision at perturbation 0 so shorten must retry."""

    COLLISION_CODE = "aaaaaaaa"
    RESOLVED_CODE = "bbbbbbbb"

    def encode(self, long_url: LongUrl) -> str:
        if long_url._perturbation_count == 0:
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

    def test_perturb_returns_new_instance_with_incremented_count(self):
        original = LongUrl("https://example.com")
        perturbed = original.perturb()

        assert perturbed is not original
        assert perturbed.url == original.url
        assert original._perturbation_count == 0
        assert perturbed._perturbation_count == 1

    def test_repeated_perturb_increments_further(self):
        url = LongUrl("https://example.com")
        twice = url.perturb().perturb()
        assert twice._perturbation_count == 2


class TestB62Encoder:
    def setup_method(self):
        self.encoder = B62Encoder()

    def test_encode_is_deterministic(self):
        url = LongUrl("https://example.com/path")
        assert self.encoder.encode(url) == self.encoder.encode(url)

    def test_encode_same_url_same_perturbation_is_stable(self):
        a = LongUrl("https://example.com", _perturbation_count=3)
        b = LongUrl("https://example.com", _perturbation_count=3)
        assert self.encoder.encode(a) == self.encoder.encode(b)

    def test_encode_includes_perturbation_count(self):
        base = LongUrl("https://example.com")
        perturbed = LongUrl("https://example.com", _perturbation_count=1)
        assert self.encoder.encode(base) != self.encoder.encode(perturbed)

    def test_different_urls_produce_different_codes(self):
        a = LongUrl("https://example.com/a")
        b = LongUrl("https://example.com/b")
        assert self.encoder.encode(a) != self.encoder.encode(b)

    def test_code_is_exactly_eight_base62_chars(self):
        code = self.encoder.encode(LongUrl("https://example.com"))
        assert len(code) == 8
        assert all(ch in BASE62 for ch in code)


class TestURLShortener:
    def setup_method(self):
        self.shortener = URLShortener()
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

    def test_custom_base_url_is_used_for_shorten_and_resolve(self):
        shortener = URLShortener(base_url="https://tiny.test/")
        long_url = LongUrl("https://example.com/custom")
        short_url = shortener.shorten(long_url)

        assert short_url.startswith("https://tiny.test/")
        assert shortener.resolve(short_url) == long_url
        with pytest.raises(InvalidUrlError):
            shortener.resolve(f"{DEFAULT_BASE}{short_url.removeprefix('https://tiny.test/')}")


class TestCollisions:
    def setup_method(self):
        self.encoder = CollisionEncoder()
        self.shortener = URLShortener(encoder=self.encoder)
        self.url_a = LongUrl("https://example.com/a")
        self.url_b = LongUrl("https://example.com/b")

    def test_second_url_is_perturbed_off_the_colliding_code(self):
        short_a = self.shortener.shorten(self.url_a)
        short_b = self.shortener.shorten(self.url_b)

        assert short_a == f"{DEFAULT_BASE}{CollisionEncoder.COLLISION_CODE}"
        assert short_b == f"{DEFAULT_BASE}{CollisionEncoder.RESOLVED_CODE}"
        assert short_a != short_b

    def test_resolve_returns_original_unperturbed_urls_after_collision(self):
        short_a = self.shortener.shorten(self.url_a)
        short_b = self.shortener.shorten(self.url_b)

        assert self.shortener.resolve(short_a) == self.url_a
        assert self.shortener.resolve(short_b) == self.url_b
        assert self.shortener.resolve(short_a)._perturbation_count == 0
        assert self.shortener.resolve(short_b)._perturbation_count == 0

    def test_first_url_stays_idempotent_after_later_collision(self):
        short_a = self.shortener.shorten(self.url_a)
        self.shortener.shorten(self.url_b)
        assert self.shortener.shorten(LongUrl("https://example.com/a")) == short_a
