"""Part C — ResilientClient: compose classification, retry, breaker and fallback.

The simulator calls ``start`` for every logical LLM call, then ``on_success``
or ``on_error`` for every attempt. You answer with ``Send`` (try a provider,
maybe after a delay) or ``GiveUp`` (user gets a static degraded answer).

Tests: tests/test_client.py, then `make compare` (6 incident tapes).

Per-call scratch space lives in ``call.state`` (a dict). Suggested keys:
    "ladder": list[str]  providers this call may use, in order
    "idx":    int        position of the provider we are currently on
    "tries":  int        attempts already made on that provider

Decision table for ``on_error`` (implement it!):

| ErrorKind        | breaker              | then                                                    |
|------------------|----------------------|---------------------------------------------------------|
| CLIENT_ERROR     | release (not health) | GiveUp("client_error") — never retry, never fail over   |
| QUOTA_EXHAUSTED  | release              | cooldown provider for quota_cooldown_s; fail over now   |
| RATE_LIMITED     | release              | cooldown provider until now + retry_after; fail over now|
| OVERLOADED /     | on_failure           | retry SAME provider after backoff.delay(tries) if       |
| SERVER_ERROR /   |                      |   tries < max_attempts_per_provider AND budget allows   |
| TIMEOUT          |                      |   AND it fits the deadline; otherwise fail over         |

Cooldowns are per provider and shared by all calls (other calls must avoid a
rate-limited provider too). When every provider in the ladder is unusable,
you may wait for a *short* (<= 5 s) rate-limit cooldown if it fits the deadline.
"""

from __future__ import annotations

import random
from typing import Any

from gameday_lab.breaker import BreakerState, Permit, SlidingWindowBreaker
from gameday_lab.errors import ErrorKind, classify, counts_toward_breaker
from gameday_lab.retry import FullJitterBackoff, RetryBudget
from gameday_lab.sim.contracts import (
    Action,
    Attempt,
    BaseClient,
    CallContext,
    GiveUp,
    ProviderError,
    ProviderInfo,
    Send,
)

RATE_LIMIT_WAIT_MAX_S = 5.0
SLOW_REASONS = ("slow_call_rate", "probe_slow")  # breaker opened because answers were slow, not failing  # only wait for short (rate-limit) cooldowns, never for quota


class ResilientClient(BaseClient):
    name = "resilient"

    def __init__(
        self,
        providers: dict[str, ProviderInfo],
        fallback_order: list[str] | tuple[str, ...],
        settings: dict[str, Any],
        seed: int = 0,
    ) -> None:
        """PROVIDED: reads the `client:` block of configs/gameday.yaml."""
        self.providers = providers
        self.order = list(fallback_order)
        self.timeout_s = float(settings.get("attempt_timeout_s", 8.0))
        self.max_attempts_per_provider = int(settings.get("max_attempts_per_provider", 2))
        self.min_time_left_s = float(settings.get("min_time_left_s", 1.0))
        self.quota_cooldown_s = float(settings.get("quota_cooldown_s", 300.0))
        self.backoff = FullJitterBackoff(
            float(settings.get("backoff_base_s", 0.25)),
            float(settings.get("backoff_cap_s", 4.0)),
            random.Random(seed),
        )
        self.budget = RetryBudget(
            float(settings.get("retry_budget_ratio", 0.1)),
            float(settings.get("retry_budget_min_per_s", 0.5)),
            float(settings.get("retry_budget_max_tokens", 20.0)),
        )
        breaker_cfg = dict(settings.get("breaker", {}))
        self.breakers = {name: SlidingWindowBreaker(name, **breaker_cfg) for name in providers}
        self.cooldown_until: dict[str, float] = {name: 0.0 for name in providers}
        # why each provider is cooling down: only short rate-limit cooldowns are worth waiting for
        self.cooldown_kind: dict[str, ErrorKind | None] = {name: None for name in providers}
        # a timeout has already burnt `attempt_timeout_s` of the user's 30 s; by default spend
        # the next attempt on a different provider instead of the one that just hung
        self.retry_on_timeout = bool(settings.get("retry_on_timeout", False))
        self.rate_limit_jitter_s = float(settings.get("rate_limit_jitter_s", 0.5))
        # when only one tool-capable provider is left, chat calls leave it to the tool calls
        self.reserve_tool_capacity = bool(settings.get("reserve_tool_capacity", True))
        # a breaker opened for SLOWNESS means "go somewhere faster"; when there is nowhere faster,
        # a slow answer beats no answer (a breaker opened for FAILURES still blocks)
        self.slow_fallback = bool(settings.get("slow_fallback", True))
        self._jitter = random.Random(seed + 1)

    # ------------------------------------------------------------------ provided helper
    def _send(self, call: CallContext, provider: str, now: float, delay: float) -> Action | None:
        """PROVIDED. Build a Send for ``provider`` (after ``delay``), or None if its breaker refuses.

        Takes a breaker permit (carried in ``tag``), and caps the attempt timeout
        so it never runs past the call's deadline. Returns GiveUp("deadline") if
        there is not enough time left for a meaningful attempt.
        """
        permit = self.breakers[provider].allow(now)
        if permit is None:
            return None
        timeout = min(self.timeout_s, call.deadline - (now + delay))
        if timeout < self.min_time_left_s:
            self.breakers[provider].release(permit, now)
            return GiveUp("deadline")
        return Send(provider, timeout_s=timeout, delay_s=delay, tag=permit)

    # ------------------------------------------------------------------ TODO
    def ladder(self, task: str) -> list[str]:
        """``self.order`` filtered by capability: a tool call never goes to a model without tool calling."""
        needs_tools = task == "tool"
        return [p for p in self.order if p in self.providers and (self.providers[p].supports_tools or not needs_tools)]

    def _route(self, call: CallContext, now: float, delay: float = 0.0) -> Action:
        st = call.state
        ladder: list[str] = st["ladder"]
        while st["idx"] < len(ladder):
            p = ladder[st["idx"]]
            if self.cooldown_until[p] <= now + delay and not self._reserved_for_tools(call, p, now):
                action = self._send(call, p, now, delay)
                if action is not None:
                    return action
            st["idx"] += 1
            st["tries"] = 0
            delay = 0.0  # a failover goes out immediately
        return self._wait_for_rate_limit(call, now)

    def _wait_for_rate_limit(self, call: CallContext, now: float) -> Action:
        """Every rung is unusable. A rate limit clears within seconds, so waiting for it beats a
        degraded answer; quota, open breakers and long waits do not."""
        ladder: list[str] = call.state["ladder"]
        waitable = [
            p for p in ladder
            if self.cooldown_kind[p] is ErrorKind.RATE_LIMITED
            and 0.0 < self.cooldown_until[p] - now <= RATE_LIMIT_WAIT_MAX_S
            and self.breakers[p].state is not BreakerState.OPEN
        ]
        if waitable:
            p = min(waitable, key=lambda name: self.cooldown_until[name])
            # spread the waiters over the next window instead of all hitting its first millisecond
            delay = self.cooldown_until[p] - now + self._jitter.uniform(0.0, self.rate_limit_jitter_s)
            if call.deadline - (now + delay) >= self.min_time_left_s:
                action = self._send(call, p, now, delay)
                if action is not None:
                    call.state["idx"] = ladder.index(p)
                    call.state["tries"] = 0
                    return action
        if self.slow_fallback:
            action = self._send_to_slow_provider(call, now)
            if action is not None:
                return action
        return GiveUp("no_provider_available")

    def _send_to_slow_provider(self, call: CallContext, now: float) -> Action | None:
        """Last rung before giving up: every provider is refused, but some only because they are SLOW
        (e.g. all four regions degraded at once). Send to the first such provider without a breaker
        permit: it is real user demand, not a retry, and the breaker keeps probing on its own."""
        if call.state.get("slow_fallback_used"):
            return None  # once per call: a failed slow attempt must not turn into an unbudgeted retry loop
        ladder: list[str] = call.state["ladder"]
        for p in ladder:
            b = self.breakers[p]
            if self.cooldown_until[p] > now or b.state is not BreakerState.OPEN:
                continue
            if not b.transitions or b.transitions[-1].reason not in SLOW_REASONS:
                continue
            timeout = min(self.timeout_s, call.deadline - now)
            if timeout < self.min_time_left_s:
                return GiveUp("deadline")
            call.state.update(idx=ladder.index(p), tries=0, slow_fallback_used=True)
            return Send(p, timeout_s=timeout, delay_s=0.0, tag=None)
        return None

    def start(self, call: CallContext, now: float) -> Action:
        self.budget.record_request(now)
        call.state.update(ladder=self.ladder(call.task), idx=0, tries=0)
        return self._route(call, now)

    def on_success(self, attempt: Attempt, now: float, latency_s: float) -> None:
        permit = attempt.tag
        if isinstance(permit, Permit):
            self.breakers[attempt.provider].on_success(permit, now, latency_s)

    def on_error(self, attempt: Attempt, err: ProviderError, now: float) -> Action:
        call, p, permit = attempt.call, attempt.provider, attempt.tag
        st = call.state
        breaker = self.breakers[p]
        kind = classify(err)
        if isinstance(permit, Permit):
            if counts_toward_breaker(kind):
                breaker.on_failure(permit, now)
            else:
                breaker.release(permit, now)
        if p in st["ladder"]:
            st["idx"] = st["ladder"].index(p)
        st["tries"] = st.get("tries", 0) + 1

        if kind is ErrorKind.CLIENT_ERROR:
            return GiveUp("client_error")  # malformed everywhere: retrying or failing over only adds load
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            self._cool_down(p, now + self.quota_cooldown_s, kind)
            return self._fail_over(call, now)
        if kind is ErrorKind.RATE_LIMITED:
            wait = err.retry_after if err.retry_after is not None else 1.0
            self._cool_down(p, now + wait, kind)
            return self._fail_over(call, now)

        # OVERLOADED / SERVER_ERROR / TIMEOUT: maybe one more try on the same provider
        if self._may_retry_same(call, p, kind, now):
            delay = self.backoff.delay(st["tries"])
            if call.deadline - (now + delay) >= self.min_time_left_s and self.budget.try_acquire_retry(now):
                action = self._send(call, p, now, delay)
                if action is not None:
                    return action
        return self._fail_over(call, now)

    def on_cancel(self, call: CallContext, tag: Any, now: float) -> None:
        if isinstance(tag, Permit):
            self.breakers[tag.breaker].release(tag, now)

    # ------------------------------------------------------------------ helpers
    def _usable(self, provider: str, now: float) -> bool:
        """Would ``provider`` take a request now? Peeks at the breaker without taking a permit."""
        if self.cooldown_until[provider] > now:
            return False
        b = self.breakers[provider]
        if b.state is BreakerState.OPEN:
            return now - b.opened_at >= b.open_duration_s
        if b.state is BreakerState.HALF_OPEN:
            return b.probes_in_flight < b.half_open_max_probes
        return True

    def _reserved_for_tools(self, call: CallContext, provider: str, now: float) -> bool:
        """Capability-aware load shedding. A chat call can be answered by any model, a tool call only by
        a tool-capable one. When ``provider`` is the LAST usable tool-capable provider (e.g. provider A is
        down and only beta is left), sending chat there spends its scarce rate limit on work a cheaper
        model can do, and the tool calls then queue behind 429 cooldowns. Skip it if a non-tool provider
        further down this call's ladder can take the chat call right now."""
        if not self.reserve_tool_capacity or call.task == "tool" or not self.providers[provider].supports_tools:
            return False
        tool_capable = [p for p in self.order if self.providers[p].supports_tools and self._usable(p, now)]
        if tool_capable != [provider]:
            return False
        ladder: list[str] = call.state["ladder"]
        rest = ladder[ladder.index(provider) + 1:]
        return any(not self.providers[p].supports_tools and self._usable(p, now) for p in rest)

    def _may_retry_same(self, call: CallContext, provider: str, kind: ErrorKind, now: float) -> bool:
        if call.state["tries"] >= self.max_attempts_per_provider:
            return False
        if kind is ErrorKind.TIMEOUT and not self.retry_on_timeout:
            return False
        return self.cooldown_until[provider] <= now

    def _fail_over(self, call: CallContext, now: float) -> Action:
        call.state["idx"] += 1
        call.state["tries"] = 0
        return self._route(call, now)

    def _cool_down(self, provider: str, until: float, kind: ErrorKind) -> None:
        # never shorten a cooldown another call already set (e.g. quota beats a rate limit)
        if until > self.cooldown_until[provider]:
            self.cooldown_until[provider] = until
            self.cooldown_kind[provider] = kind
