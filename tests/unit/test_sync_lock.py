from codex_telegram_gateway.sync_lock import try_acquire_sync_lock


def test_try_acquire_sync_lock_allows_only_one_holder(tmp_path) -> None:
    lock_path = tmp_path / "gateway.lock"

    first = try_acquire_sync_lock(lock_path)
    assert first is not None

    second = try_acquire_sync_lock(lock_path)
    assert second is None

    first.release()

    third = try_acquire_sync_lock(lock_path)
    assert third is not None
    third.release()
