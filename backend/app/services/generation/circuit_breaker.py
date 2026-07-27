"""
circuit_breaker.py
==================
Circuit Breaker pattern & Selective Retry Policy for LLM and Image Providers.

States:
- CLOSED: Requests proceed normally. Failure counts increment on error.
- OPEN: Requests fail fast immediately by throwing CircuitBreakerOpenException.
- HALF_OPEN: Probe state after recovery timeout. Success resets to CLOSED; failure re-opens.

Selective Retry Policy:
- RETRY: HTTP 429, 500, 502, 503, 504, and network connection/timeout exceptions.
- NO RETRY: HTTP 400, 401, 403, 404, schema/validation errors. Fail fast!
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Any, Callable, Optional, Set, Type, Tuple

logger = logging.getLogger("branding_engine.generation.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    """Raised when a request is attempted while the circuit breaker is OPEN."""

    def __init__(self, provider_name: str, reset_in_seconds: float):
        self.provider_name = provider_name
        self.reset_in_seconds = reset_in_seconds
        super().__init__(
            f"Circuit breaker for provider '{provider_name}' is OPEN. "
            f"Retry after {reset_in_seconds:.1f} seconds."
        )


class CircuitBreaker:
    """Stateful circuit breaker tracking provider health."""

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        recovery_time_seconds: float = 60.0,
    ):
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change_time: float = time.time()

    def _update_state(self) -> CircuitState:
        """Evaluate state transitions based on elapsed recovery time."""
        now = time.time()
        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (now - self.last_failure_time) >= self.recovery_time_seconds:
                logger.info(
                    f"[CIRCUIT BREAKER] Transitioning '{self.provider_name}' from OPEN to HALF_OPEN."
                )
                self.state = CircuitState.HALF_OPEN
                self.last_state_change_time = now
        return self.state

    def allow_request(self) -> bool:
        """Check whether execution is allowed through the circuit."""
        state = self._update_state()
        if state == CircuitState.OPEN:
            return False
        return True

    def record_success(self) -> None:
        """Record a successful execution, resetting failure counters."""
        if self.state != CircuitState.CLOSED:
            logger.info(
                f"[CIRCUIT BREAKER] Success recorded for '{self.provider_name}'. "
                f"Resetting state to CLOSED."
            )
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    def record_failure(self) -> None:
        """Record a failure, tripping the circuit if threshold is breached."""
        now = time.time()
        self.failure_count += 1
        self.last_failure_time = now

        logger.warning(
            f"[CIRCUIT BREAKER] Failure recorded for '{self.provider_name}'. "
            f"Current count: {self.failure_count}/{self.failure_threshold}"
        )

        if self.failure_count >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            logger.error(
                f"[CIRCUIT BREAKER TRIPPED] Provider '{self.provider_name}' state -> OPEN. "
                f"Will probe in {self.recovery_time_seconds}s."
            )
            self.state = CircuitState.OPEN
            self.last_state_change_time = now

    def time_until_reset(self) -> float:
        """Return remaining seconds before OPEN circuit enters HALF_OPEN."""
        if self.state != CircuitState.OPEN or not self.last_failure_time:
            return 0.0
        elapsed = time.time() - self.last_failure_time
        return max(0.0, self.recovery_time_seconds - elapsed)


def is_retriable_error(exc: Exception) -> bool:
    """Determine if an exception should trigger an automated retry.

    RETRYABLE:
    - 429 Rate Limit
    - 500, 502, 503, 504 Server Errors
    - Network / Connection / Timeout exceptions

    NON-RETRYABLE:
    - 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found
    - JSON parsing or validation errors
    """
    exc_str = str(exc).lower()

    # Explicit HTTP status checks in exception message or attributes
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code is not None:
        if status_code in (429, 500, 502, 503, 504):
            return True
        if status_code in (400, 401, 403, 404):
            return False

    # Check for rate limit or server error keywords in exception string
    retriable_keywords = [
        "429", "500", "502", "503", "504",
        "timeout", "timed out", "connection error", "connection refused",
        "server error", "temporarily unavailable", "rate limit", "too many requests"
    ]
    if any(keyword in exc_str for keyword in retriable_keywords):
        return True

    # Non-retriable auth or bad request keywords
    non_retriable_keywords = [
        "400", "401", "403", "404", "quota", "unauthorized", "forbidden",
        "invalid api key", "bad request", "validationerror"
    ]
    if any(keyword in exc_str for keyword in non_retriable_keywords):
        return False

    # Default to False for unknown errors (fail-fast)
    return False


async def execute_with_retry(
    func: Callable[..., Any],
    *args: Any,
    circuit_breaker: Optional[CircuitBreaker] = None,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    on_retry: Optional[Callable[[int], None]] = None,
    **kwargs: Any,
) -> Any:
    """Execute an async callable with selective retry policies and circuit breaker safety.

    Args:
        func: Async function to execute.
        circuit_breaker: Optional CircuitBreaker instance.
        max_retries: Maximum number of retry attempts for retriable errors.
        initial_backoff: Initial sleep duration in seconds.
        backoff_factor: Exponential backoff multiplier.
        jitter: Add random noise to sleep interval to prevent thundering herd.
        on_retry: Optional callback invoked with the current retry attempt count.

    Returns:
        Result of func call.

    Raises:
        CircuitBreakerOpenException: If circuit is OPEN.
        Exception: Original exception if non-retriable or retries exhausted.
    """
    if circuit_breaker:
        if not circuit_breaker.allow_request():
            reset_in = circuit_breaker.time_until_reset()
            raise CircuitBreakerOpenException(circuit_breaker.provider_name, reset_in)

    attempt = 0
    current_backoff = initial_backoff

    while True:
        attempt += 1
        try:
            result = await func(*args, **kwargs)
            if circuit_breaker:
                circuit_breaker.record_success()
            return result

        except Exception as exc:
            if circuit_breaker:
                circuit_breaker.record_failure()

            retriable = is_retriable_error(exc)
            if not retriable or attempt > max_retries:
                logger.error(
                    f"[RETRY POLICY] Non-retriable exception or retries exhausted "
                    f"(attempt {attempt}/{max_retries + 1}): {exc}"
                )
                raise exc

            sleep_time = current_backoff
            if jitter:
                sleep_time += random.uniform(0, 0.5 * current_backoff)

            if on_retry:
                on_retry(attempt)

            logger.warning(
                f"[RETRY POLICY] Retriable error (attempt {attempt}/{max_retries + 1}). "
                f"Retrying in {sleep_time:.2f}s... Error: {exc}"
            )
            await asyncio.sleep(sleep_time)
            current_backoff *= backoff_factor
