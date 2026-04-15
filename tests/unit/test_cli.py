from codex_telegram_gateway import cli


class _FakeState:
    def __init__(self) -> None:
        self._counts = iter([3, 4, 1])

    def pending_inbound_count(self) -> int:
        return next(self._counts)


class _FakeService:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def link_loaded_threads(self) -> None:
        self._calls.append("link_loaded_threads")


class _FakeDaemon:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def poll_telegram_once(self) -> None:
        self._calls.append("poll_telegram_once")

    def deliver_inbound_once(self) -> None:
        self._calls.append("deliver_inbound_once")

    def sync_codex_once(self) -> None:
        self._calls.append("sync_codex_once")

    def run_lifecycle_sweeps(self) -> None:
        self._calls.append("run_lifecycle_sweeps")


def test_run_sync_iteration_runs_lifecycle_sweeps_after_sync() -> None:
    calls: list[str] = []

    result = cli._run_sync_iteration(
        _FakeState(),
        _FakeService(calls),
        _FakeDaemon(calls),
    )

    assert calls == [
        "link_loaded_threads",
        "poll_telegram_once",
        "deliver_inbound_once",
        "sync_codex_once",
        "run_lifecycle_sweeps",
    ]
    assert result == {
        "pending_before": 3,
        "pending_after_poll": 4,
        "pending_after_deliver": 1,
    }
