import os
from typing import Optional
from threading import Thread

from loguru import logger

from .proxy import Executor, Proxy
from .events import EventLoop

event_loop: Optional[EventLoop] = None
event_thread: Optional[Thread] = None
executor: Optional[Executor] = None
# The "root" interface to JavaScript with FFID 0
global_jsi: Optional[Proxy] = None
# Currently this breaks GC
fast_mode = False
# Whether we need patches for legacy node versions
node_emitter_patches = False


if ("DEBUG" in os.environ) and ("jspybridge" in os.getenv("DEBUG", "")):
    debug = logger.debug
else:
    debug = lambda *a: None


def is_main_loop_active():
    if not event_thread or not event_loop:
        return False
    return event_thread.is_alive() and event_loop.active


dead = "\n** The Node process has crashed. Please restart the runtime to use JS APIs. **\n"
