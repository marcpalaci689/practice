'''
URL shortener.

Functional requirements
- Valid long URLs start with http:// or https://. Anything else raises InvalidUrlError.
- shorten(long_url) returns a full short URL: {base_url}{code}.
  Default base_url is https://sho.rt/. Code is exactly 8 base62 characters [A-Za-z0-9].
- Shortening the same long URL repeatedly returns the same short URL.
- Two different long URLs never share a short code.
- resolve(shorten(url)) returns the original LongUrl exactly.
- resolve takes the full short URL (not a bare code) and parses the code by
  stripping self.base_url. A custom base_url must work; do not hardcode the host.
- A well-formed but unseen short URL raises UnknownCodeError.
- A malformed short URL (wrong prefix, wrong length, non-base62 suffix, or a
  bare code) raises InvalidUrlError.
- Single-process, in-memory only. No persistence or distributed concurrency.

API
- LongUrl(url): frozen validated value object. Identity is the URL string only.
  Perturbation is not stored on LongUrl.
- URLShortener.shorten(long_url: LongUrl) -> str
- URLShortener.resolve(short_url: str) -> LongUrl
- ShorteningEncoder.encode(long_url, perturbation: int | None = None) -> str

Encoding
- B62Encoder hashes the (possibly perturbed) URL with SHA-256, then base62-encodes
  to exactly 8 characters.
- First encode attempt uses perturbation=None and hashes the URL as-is.
- On collision, shorten retries with perturbation 0, 1, 2, ... as a random seed.
  The seed deterministically shuffles the URL characters before hashing.
- Same (url, perturbation) pair always produces the same code.

Storage
- Bidirectional in-memory maps: LongUrl -> code and code -> LongUrl.
- Always store the original LongUrl the caller passed in. Perturbation is only
  an encode() argument and is never written into the maps.

Collision handling
- If the long URL is already stored, return the existing short URL.
- If a newly generated code is already bound to a different URL, increment
  the perturbation seed and re-encode. Cap retries to avoid an infinite loop.
'''

import hashlib
import random
import string
from dataclasses import dataclass, field
from typing import Protocol

BASE62_ALPHABET = string.ascii_letters + string.digits


class InvalidUrlError(Exception):
    '''
    Raised  when a URL in invalid
    '''
    pass

class UnknownCodeError(Exception):
    '''
    Raised when a code is unknown
    '''
    pass


@dataclass(frozen=True)
class LongUrl:
    url: str
    
    def __post_init__(self):
        '''
        validate the URL
        '''
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise InvalidUrlError(f"URL must start with http:// or https://: {self.url!r}")


class ShorteningEncoder(Protocol):
    def encode(self, long_url: LongUrl, perturbation: int | None = None) -> str:
        '''
        encode the long url to get a code. perturbation is None on the first
        attempt; after a collision it is a monotonically increasing integer
        used as a deterministic random seed.
        '''
        ...

class B62Encoder(ShorteningEncoder):
    def encode(self, long_url: LongUrl, perturbation: int | None = None) -> str:
        '''
        Hash a (possibly seeded-perturbed) URL, then base62-encode to 8 chars.
        '''
        payload = self._perturbed_url(long_url.url, perturbation).encode()
        value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
        chars: list[str] = []
        for _ in range(8):
            value, remainder = divmod(value, 62)
            chars.append(BASE62_ALPHABET[remainder])
        return "".join(chars)

    def _perturbed_url(self, url: str, perturbation: int | None) -> str:
        if perturbation is None:
            return url
        chars = list(url)
        random.Random(perturbation).shuffle(chars)
        return "".join(chars)

@dataclass
class URLShortener:
    base_url: str = field(default="https://sho.rt/")
    encoder: ShorteningEncoder = field(default_factory=B62Encoder)

    _long_url_to_code: dict[LongUrl, str] = field(default_factory=dict, init=False)
    _code_to_long_url: dict[str, LongUrl] = field(default_factory=dict, init=False)
    
    def shorten(self, long_url: LongUrl) -> str:
        '''
        Return https://sho.rt/<code> (self.base_url + code).
        If this long url was already shortened, return the existing short URL.
        On code collision, re-encode with perturbation None, then 0, 1, 2, ...
        Always store the original LongUrl in the maps.
        '''
        if long_url in self._long_url_to_code:
            return self.base_url + self._long_url_to_code[long_url]

        perturbation: int | None = None
        for _ in range(64):
            code = self.encoder.encode(long_url, perturbation)
            owner = self._code_to_long_url.get(code)
            if owner is None:
                self._long_url_to_code[long_url] = code
                self._code_to_long_url[code] = long_url
                return self.base_url + code
            perturbation = 0 if perturbation is None else perturbation + 1
        raise RuntimeError("could not allocate a unique short code")

    def resolve(self, short_url: str) -> LongUrl:
        '''
        Parse short_url using base_url, then look up the extracted code.
        '''
        code = self._parse_short_url(short_url)
        try:
            return self._code_to_long_url[code]
        except KeyError:
            raise UnknownCodeError(f"unknown short code: {code}") from None

    def _parse_short_url(self, short_url: str) -> str:
        '''
        Strip self.base_url from short_url and return the 8-char code.
        Raise InvalidUrlError if the prefix does not match or the suffix
        is not exactly 8 base62 characters.
        '''
        if not short_url.startswith(self.base_url):
            raise InvalidUrlError(
                f"short URL must start with {self.base_url!r}: {short_url!r}"
            )
        code = short_url[len(self.base_url):]
        if len(code) != 8 or any(ch not in BASE62_ALPHABET for ch in code):
            raise InvalidUrlError(f"short URL code must be 8 base62 characters: {code!r}")
        return code
