"""Per-invocation outbound request budget (proposal Section 6.4, 10.3).

The budget counts every HTTP attempt, including retries. When exhausted the current
operation raises ``bound_exceeded``; tools that page or traverse should check
:meth:`Budget.remaining` before issuing optional follow-up calls and report truncation
instead of failing where possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import EvsMcpError


@dataclass
class Budget:
    max_requests: int
    used: int = 0
    retries: int = 0
    exhausted: bool = field(default=False, init=False)

    @property
    def remaining(self) -> int:
        return max(self.max_requests - self.used, 0)

    def take(self, *, retry: bool = False) -> None:
        if self.used >= self.max_requests:
            self.exhausted = True
            raise EvsMcpError(
                "bound_exceeded",
                "outbound request budget exhausted",
                details={"bound": "maxRequests", "limit": self.max_requests, "used": self.used},
            )
        self.used += 1
        if retry:
            self.retries += 1
