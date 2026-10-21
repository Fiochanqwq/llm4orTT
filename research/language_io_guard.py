"""Runtime guards for pure prompt construction and zero-network calculations."""
import contextvars
import sys
from contextlib import contextmanager

_prompt = contextvars.ContextVar("language_prompt_no_file_io", default=False)
_offline = contextvars.ContextVar("language_zero_network", default=False)


def _audit(event, args):
    if _prompt.get() and event == "open":
        raise PermissionError("Prompt construction cannot open files, including truth: " + str(args[0]))
    if _offline.get() and event in ("socket.connect", "socket.connect_ex", "subprocess.Popen"):
        raise PermissionError("Zero-call calculation forbids network connections and child processes")


sys.addaudithook(_audit)


@contextmanager
def prompt_io_guard():
    token = _prompt.set(True)
    try:
        yield
    finally:
        _prompt.reset(token)


@contextmanager
def zero_call_guard():
    token = _offline.set(True)
    try:
        yield
    finally:
        _offline.reset(token)
