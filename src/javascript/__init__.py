# This file contains all the exposed modules
import atexit
import inspect
import os
import sys
import threading
from typing import Optional, Union, Dict

from . import config, proxy, events
from . import json_patch  # noqa: F401


def init():
    global console, globalThis, RegExp, start, stop, abort
    if config.event_loop:
        return  # Do not start event loop again
    config.event_loop = events.EventLoop()
    start = config.event_loop.startThread
    stop = config.event_loop.stopThread
    abort = config.event_loop.abortThread
    config.event_thread = threading.Thread(target=config.event_loop.loop, args=(), daemon=True)
    config.event_thread.start()
    config.executor = proxy.Executor(config.event_loop)
    global_jsi = config.global_jsi = proxy.Proxy(config.executor, 0)
    console = config.global_jsi.console  # TODO: Remove this in 1.0
    globalThis = config.global_jsi.globalThis
    RegExp = config.global_jsi.RegExp
    atexit.register(config.event_loop.on_exit)
    needsNodePatches = global_jsi.needsNodePatches
    if not needsNodePatches:
        config.node_emitter_patches = False
    elif needsNodePatches():
        config.node_emitter_patches = True


init()


def terminate():
    if config.event_loop:
        config.event_loop.stop()


def require(name: str, version: Optional[str] = None) -> Union[proxy.Proxy, Dict[str, proxy.Proxy]]:
    if not config.global_jsi:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `require`.")
    calling_dir: Optional[str] = None
    jsi_require = config.global_jsi.require
    if not jsi_require:
        raise RuntimeError("JSI does not support require.")
    if name.startswith("."):
        # Some code to extract the caller's file path, needed for relative imports
        try:
            namespace = sys._getframe(1).f_globals  # type: ignore
            cwd = os.getcwd()
            rel_path = namespace["__file__"]
            abs_path = os.path.join(cwd, rel_path)
            calling_dir = os.path.dirname(abs_path)
        except Exception:
            # On Notebooks, the frame info above does not exist, so assume the CWD as caller
            calling_dir = os.getcwd()

    return jsi_require(name, version, calling_dir, timeout=900)


def eval_js(js: str):
    if not config.global_jsi:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `require`.")
    jsi_eval = config.global_jsi.evaluateWithContext
    if not jsi_eval:
        raise RuntimeError("JSI does not support eval.")
    frame = inspect.currentframe()
    if not frame:
        return None
    rv = None
    try:
        local_vars = {}
        for local in frame.f_back.f_locals:  # type: ignore
            if not local.startswith("__"):
                local_vars[local] = frame.f_back.f_locals[local]  # type: ignore
        rv = jsi_eval(js, local_vars, forceRefs=True)
    finally:
        del frame
    return rv


def AsyncTask(start: bool = False):
    if not config.event_loop:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `AsyncTask.")
    loop = config.event_loop

    def decor(fn):
        fn.is_async_task = True
        t = loop.newTaskThread(fn)
        if start:
            t.start()
        return t
    return decor


# You must use this Once decorator for an EventEmitter in Node.js, otherwise
# you will not be able to off an emitter.
def On(emitter, event):
    # print("On", emitter, event,onEvent)
    if not config.event_loop:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `AsyncTask.")
    loop = config.event_loop

    def decor(_fn):
        # Once Colab updates to Node 16, we can remove this.
        # Here we need to manually add in the `this` argument for consistency in Node versions.
        # In JS we could normally just bind `this` but there is no bind in Python.
        if config.node_emitter_patches:

            def handler(*args, **kwargs):
                _fn(emitter, *args, **kwargs)

            fn = handler
        else:
            fn = _fn

        emitter.on(event, fn)
        # We need to do some special things here. Because each Python object
        # on the JS side is unique, EventEmitter is unable to equality check
        # when using .off. So instead we need to avoid the creation of a new
        # PyObject on the JS side. To do that, we need to persist the FFID for
        # this object. Since JS is the autoritative side, this FFID going out
        # of refrence on the JS side will cause it to be destoryed on the Python
        # side. Normally this would be an issue, however it's fine here.
        ffid = getattr(fn, "iffid")
        setattr(fn, "ffid", ffid)
        loop.callbacks[ffid] = fn
        return fn

    return decor


# The extra logic for this once function is basically just to prevent the program
# from exiting until the event is triggered at least once.
def Once(emitter, event):
    if not config.event_loop:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `AsyncTask.")
    loop = config.event_loop

    def decor(fn):
        i = hash(fn)

        def handler(*args, **kwargs):
            if config.node_emitter_patches:
                fn(emitter, *args, **kwargs)
            else:
                fn(*args, **kwargs)
            del loop.callbacks[i]

        emitter.once(event, handler)
        loop.callbacks[i] = handler

    return decor


def off(emitter, event, handler):
    if not config.event_loop:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `AsyncTask.")
    emitter.off(event, handler)
    del config.event_loop.callbacks[getattr(handler, "ffid")]


def once(emitter, event):
    if not config.global_jsi:
        raise RuntimeError("JSI not initialized. Please call `init()` before using `AsyncTask.")
    jsi_once = config.global_jsi.once
    if not jsi_once:
        raise RuntimeError("JSI does not support once.")
    val = jsi_once(emitter, event, timeout=1000)
    return val
