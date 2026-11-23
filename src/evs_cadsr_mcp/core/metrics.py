"""In-process metrics with a Prometheus text exposition (proposal 10.6). No dependency.

Counters and histograms keyed by label tuples; ``render()`` emits the text format that
Prometheus / the CloudWatch agent scrape from ``/metrics``.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable

LATENCY_BUCKETS_MS = (25, 50, 100, 250, 500, 800, 1500, 3000, 5000, 10000)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._hist: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(lambda: [0.0] * (len(LATENCY_BUCKETS_MS) + 1))
        self._hist_sum: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._help: dict[str, str] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted((labels or {}).items()))

    def describe(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def observe_ms(self, name: str, ms: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            k = self._key(name, labels)
            buckets = self._hist[k]
            for i, bound in enumerate(LATENCY_BUCKETS_MS):
                if ms <= bound:
                    buckets[i] += 1
            buckets[-1] += 1  # +Inf
            self._hist_sum[k] += ms

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {f"{n}{_fmt(lbl)}": v for (n, lbl), v in self._counters.items()}

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            names = {n for n, _ in self._counters} | {n for n, _ in self._hist} | {n for n, _ in self._gauges}
            for name in sorted(names):
                if name in self._help:
                    lines.append(f"# HELP {name} {self._help[name]}")
                kind = "histogram" if any(n == name for n, _ in self._hist) else "gauge" if any(n == name for n, _ in self._gauges) else "counter"
                lines.append(f"# TYPE {name} {kind}")
                for (n, lbl), v in sorted(self._counters.items()):
                    if n == name:
                        lines.append(f"{name}{_fmt(lbl)} {_num(v)}")
                for (n, lbl), v in sorted(self._gauges.items()):
                    if n == name:
                        lines.append(f"{name}{_fmt(lbl)} {_num(v)}")
                for (n, lbl), buckets in sorted(self._hist.items()):
                    if n != name:
                        continue
                    for i, bound in enumerate(LATENCY_BUCKETS_MS):
                        lines.append(f"{name}_bucket{_fmt(lbl + (('le', str(bound)),))} {_num(buckets[i])}")
                    lines.append(f"{name}_bucket{_fmt(lbl + (('le', '+Inf'),))} {_num(buckets[-1])}")
                    lines.append(f"{name}_count{_fmt(lbl)} {_num(buckets[-1])}")
                    lines.append(f"{name}_sum{_fmt(lbl)} {_num(self._hist_sum[(n, lbl)])}")
        return "\n".join(lines) + "\n"


def _fmt(labels: Iterable[tuple[str, str]]) -> str:
    items = list(labels)
    if not items:
        return ""
    return "{" + ",".join(f'{k}="{str(v).replace(chr(34), chr(39))}"' for k, v in items) + "}"


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.3f}"


METRICS = Metrics()
METRICS.describe("ecm_tool_calls_total", "Tool invocations by tool, profile and status")
METRICS.describe("ecm_tool_latency_ms", "Tool latency in milliseconds")
METRICS.describe("ecm_outbound_requests_total", "Upstream HTTP attempts attributed to tool calls")
METRICS.describe("ecm_truncations_total", "Results truncated, by bound")
METRICS.describe("ecm_rate_limit_rejections_total", "Calls rejected by the per-client rate limiter")
METRICS.describe("ecm_scope_denials_total", "Calls rejected for missing scopes")
METRICS.describe("ecm_cache_hits_total", "Cache hits by tier")
METRICS.describe("ecm_active_release_info", "Active NCIt release (label), value 1")
