"""Hold a per-directory lock for the lifetime of the caller's file handle."""
import os


def lock_file(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
