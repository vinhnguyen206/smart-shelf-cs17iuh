"""
Shared BLE connection gate for the Jetson's single Bluetooth adapter.

The shelf has 3 BLE peripherals (2 loadcells + the xG26 sensor) driven from
two different asyncio loops/threads. BlueZ on one adapter can hold several
*established* links, but only ONE connect/scan handshake at a time — doing
them concurrently causes "Operation already in progress" and knocks existing
links down with "Software caused connection abort".

This gate serializes just the connect/scan phase across every device and
loop. Hold it only around connect + start_notify (and around a scan), then
release so the steady-state notify/read loops all run in parallel.

Usage (inside async code):
    got = await ble_lock.acquire()
    try:
        ... connect + start_notify ...
    finally:
        if got:
            ble_lock.release()
"""
import asyncio
import functools
import threading

# One global mutex for the single physical adapter.
_lock = threading.Lock()


async def acquire(timeout=40):
    """Acquire the adapter gate without blocking the event loop.

    Runs the blocking lock.acquire in a worker thread. Returns True if the
    gate was taken, False on timeout (caller proceeds best-effort so a stuck
    device can never deadlock the others forever)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(_lock.acquire, True, timeout))


def release():
    """Release the gate. Safe to call even if not held (no-op then)."""
    try:
        _lock.release()
    except RuntimeError:
        pass
