from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LlmCall


class DbLlmBudget:
    def __init__(self, session_factory: Callable[[], Session], max_calls_per_day: int):
        self._session_factory = session_factory
        self.max_calls_per_day = max_calls_per_day

    def calls_today(self) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._session_factory() as s:
            return s.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.started_at >= start)) or 0

    def try_acquire(self) -> bool:
        return self.calls_today() < self.max_calls_per_day

    def record(self, *, file_sha256: str, model: str, duration_ms: int, success: bool,
               prompt_tokens: int | None, completion_tokens: int | None, error: str | None) -> None:
        with self._session_factory() as s:
            s.add(LlmCall(file_sha256=file_sha256, model=model, duration_ms=duration_ms, success=success,
                          prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, error=error))
            s.commit()
