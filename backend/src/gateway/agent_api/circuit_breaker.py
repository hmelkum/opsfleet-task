"""
Circuit breaker in front of the agent.

After ``failure_threshold`` consecutive failures (unreachable, timeout, 5xx) the
circuit opens: requests get the fallback message immediately instead of waiting
on a dead agent. After ``reset_timeout_s`` one trial request goes through
(half-open); its success closes the circuit, its failure opens it again.
"""
import time
from collections.abc import Callable
from enum import StrEnum, auto

from src.core.observability.events import emit


class CircuitState(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        reset_timeout_s: float,
        clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._clock() - self._opened_at >= self._reset_timeout_s:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow_request(self) -> bool:
        match self.state:
            case CircuitState.CLOSED:
                return True
            case CircuitState.OPEN:
                return False
            case CircuitState.HALF_OPEN:
                if self._trial_in_flight:
                    return False
                self._trial_in_flight = True
                return True

    def record_success(self) -> None:
        if self._opened_at is not None:
            emit("agent_circuit", state=CircuitState.CLOSED.value)
        self._failures = 0
        self._opened_at = None
        self._trial_in_flight = False

    def record_failure(self) -> None:
        self._failures += 1
        self._trial_in_flight = False
        if self._opened_at is not None or self._failures >= self._failure_threshold:
            self._opened_at = self._clock()
            emit("agent_circuit", state=CircuitState.OPEN.value, consecutive_failures=self._failures)
