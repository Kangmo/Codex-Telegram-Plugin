import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class SyncLock:
    """Advisory file lock for the single Telegram background poller."""

    path: Path
    handle: TextIO

    def release(self) -> None:
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def try_acquire_sync_lock(lock_path: Path) -> SyncLock | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return SyncLock(path=lock_path, handle=handle)
