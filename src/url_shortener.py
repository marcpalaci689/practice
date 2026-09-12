'''
Build a URL shotener.

For this exercise, assume that:

Valid long URLs start with http:// or https://
The short URL format is:
https://sho.rt/<code>
<code> is exactly 8 characters
Shortening the same long URL repeatedly must return the same short URL
Two different long URLs must never resolve to the same short code
resolve(shorten(url)) must return the original URL exactly
Resolving an unknown code should fail cleanly
You can assume a single-process, local application for now
You do not need to solve distributed concurrency yet
'''

import hashlib
import string
from dataclasses import dataclass, field, replace
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
    _perturbation_count: int = 0
    
    def perturb(self) -> "LongUrl":
        '''
        Return a new LongUrl with an incremented perturbation count.
        Used only as a temporary encode() input; never store the result
        as a map key.
        '''
        return replace(self, _perturbation_count=self._perturbation_count + 1)
    
    def __post_init__(self):
        '''
        validate the URL
        '''
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise InvalidUrlError(f"URL must start with http:// or https://: {self.url!r}")


class ShorteningEncoder(Protocol):
    def encode(self, long_url: LongUrl) -> str:
        '''
        encode the long url to get a code
        '''
        ...

class B62Encoder(ShorteningEncoder):
    def encode(self, long_url: LongUrl) -> str:
        '''
        encode the long url to get a code. This encoding should use a hashing function followed
        by a base62 encoding. The hashing should take into account both the url and the 
        perturbation count.
        '''
        payload = f"{long_url.url}\0{long_url._perturbation_count}".encode()
        value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
        chars: list[str] = []
        for _ in range(8):
            value, remainder = divmod(value, 62)
            chars.append(BASE62_ALPHABET[remainder])
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
        On code collision with a different long url, perturb a copy and
        re-encode until no collision is found. Always store the original
        (unperturbed) LongUrl in the maps.
        '''
        if long_url in self._long_url_to_code:
            return self.base_url + self._long_url_to_code[long_url]

        candidate = long_url
        for _ in range(64):
            code = self.encoder.encode(candidate)
            owner = self._code_to_long_url.get(code)
            if owner is None:
                self._long_url_to_code[long_url] = code
                self._code_to_long_url[code] = long_url
                return self.base_url + code
            candidate = candidate.perturb()
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
