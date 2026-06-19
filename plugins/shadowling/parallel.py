#!/usr/bin/env python3
"""parallel.py - generic concurrency + reliability primitives (stdlib only).

No knowledge of claude or the DB: fan_out runs a dict of thunks in a thread pool
and partitions results into ok/failed; with_retry wraps a single thunk with
exponential backoff for transient failures. Shared by debrief.py and loot.py so
neither re-implements the fan-out / retry machinery.
"""

import concurrent.futures
import sys
import time


def log(msg):
    """Emit a progress line to STDERR (flushed) so a long fan-out is visible live
    instead of a frozen line; STDOUT stays reserved for the relayed summary."""
    print(msg, file=sys.stderr, flush=True)


def fan_out(jobs, *, max_workers):
    """Run `jobs` (name -> zero-arg callable) concurrently in a thread pool.
    Returns (ok, failed): ok maps name -> return value, failed maps name -> the
    Exception it raised. A thunk that raises is captured into `failed` — fan_out
    itself never raises for a job failure. Each job's start, duration, and
    OK/ERROR streams to stderr via log()."""
    ok, failed, started = {}, {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for name, fn in jobs.items():
            started[name] = time.monotonic()
            futures[pool.submit(fn)] = name
            log(f"    → {name} running")
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            dt = time.monotonic() - started[name]
            try:
                ok[name] = fut.result()
                log(f"    ✓ {name} OK {dt:.0f}s")
            except Exception as e:  # capture per-job; the run continues
                failed[name] = e
                log(f"    ✗ {name} ERROR {dt:.0f}s — {e}")
    return ok, failed


def with_retry(fn, *, attempts=3, backoff=2.0, retry_on=Exception, sleep=time.sleep):
    """Call fn(); on a `retry_on` exception, wait backoff*2**i and retry, up to
    `attempts` total calls. Re-raises the last exception after the final attempt.
    An exception NOT matching `retry_on` propagates immediately. `sleep` is
    injectable so tests don't actually wait."""
    for i in range(attempts):
        try:
            return fn()
        except retry_on:
            if i + 1 >= attempts:
                raise  # final attempt: re-raise the active exception (never None)
            sleep(backoff * (2**i))
    raise RuntimeError("with_retry needs attempts >= 1")
