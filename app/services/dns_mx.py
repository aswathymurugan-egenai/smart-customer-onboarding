"""Async MX lookup with the RFC 5321 implicit-MX fallback."""

from __future__ import annotations

import dns.asyncresolver
import dns.exception
import dns.name
import dns.resolver

from app.services.ports import MxLookup


class AsyncMxResolver:
    """Checks that a domain accepts mail, within a fixed lifetime per query."""

    def __init__(
        self, lifetime_seconds: float, resolver: dns.asyncresolver.Resolver | None = None
    ) -> None:
        self._lifetime = lifetime_seconds
        self._resolver = resolver or dns.asyncresolver.Resolver()

    async def lookup(self, domain: str) -> MxLookup:
        """Return `pass` for MX or address records, `fail` for none, `unknown` on resolver trouble.

        A null MX record (a single exchange of `.`) declares that the domain accepts no mail.
        """
        try:
            answer = await self._resolver.resolve(domain, "MX", lifetime=self._lifetime)
            exchanges = [record.exchange for record in answer]
            return "fail" if all(name == dns.name.root for name in exchanges) else "pass"
        except dns.resolver.NXDOMAIN:
            return "fail"
        except dns.resolver.NoAnswer:
            return await self._implicit_mx(domain)
        except dns.exception.DNSException:
            return "unknown"

    async def _implicit_mx(self, domain: str) -> MxLookup:
        for record_type in ("A", "AAAA"):
            try:
                await self._resolver.resolve(domain, record_type, lifetime=self._lifetime)
            except dns.resolver.NoAnswer:
                continue
            except dns.resolver.NXDOMAIN:
                return "fail"
            except dns.exception.DNSException:
                return "unknown"
            return "pass"
        return "fail"
