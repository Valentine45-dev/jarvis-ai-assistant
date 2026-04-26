"""
Internet RTT and interface throughput helpers for the HUD (bottom bar).

RTT: prefer ICMP (system ping) to rotating public DNS/anycast; on failure, TCP
connect latency to 1.1.1.1:443. Values are not comparable across modes but both
indicate “reachability + delay” for display.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from typing import Sequence

import psutil

# Rotate to reduce per-host cache bias and spot local-only failures.
_PING_HOSTS_ICMP: tuple[str, ...] = ("1.1.1.1", "8.8.8.8", "1.0.0.1", "9.9.9.9")
_TCP_HOST = "1.1.1.1"
_TCP_PORT = 443

# Round-robin index (module-level: advanced probe alternation).
_icmp_index = 0


def _subprocess_kw() -> dict:
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _parse_icmp_time_ms(text: str) -> int | None:
    """Parse one ping reply line: English `time=12ms`, `time<1ms`, or French `temps=12ms`."""
    if not text:
        return None
    low = text.lower()
    if "timed out" in low or "inaccessible" in low or "could not find" in low:
        return None
    if re.search(r"time\s*<1ms", text, re.I) or re.search(r"temps\s*<1ms", text, re.I):
        return 1
    m = re.search(r"(?:time|temps)\s*[=:]\s*<?\s*(\d+)\s*ms", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r"= (\d+)ms", text)  # some locales
    if m2:
        return int(m2.group(1))
    return None


def icmp_ping_ms(host: str, timeout_s: float = 2.5) -> int | None:
    """One ICMP round-trip via OS `ping` (ms), or None if unavailable / timeout."""
    if sys.platform == "win32":
        # -n count, -w timeout in milliseconds for each reply
        args = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        # -c count; timeout: GNU uses -W (seconds), macOS -W (milliseconds) for wait
        if sys.platform == "darwin":
            args = ["ping", "-c", "1", "-W", str(int(timeout_s * 1000)), host]
        else:
            w = max(1, int(timeout_s))
            args = ["ping", "-c", "1", "-W", str(w), host]

    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s + 0.5,
            **_subprocess_kw(),
        )
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    if r.returncode not in (0, 1) and "time=" not in (r.stdout or "") and "temps=" not in (r.stdout or ""):
        # Some OS return 1 on unreachable; still try to parse
        if not (r.stdout or r.stderr):
            return None
    block = (r.stdout or "") + "\n" + (r.stderr or "")
    for line in block.splitlines():
        t = _parse_icmp_time_ms(line)
        if t is not None:
            return t
    t = _parse_icmp_time_ms(block)
    return t


def tcp_connect_rtt_ms(host: str, port: int, timeout_s: float = 3.0) -> int | None:
    """TCP connect RTT in ms (coarser than ICMP; works when ping is blocked)."""
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout_s)
    except OSError:
        return None
    try:
        return max(0, int((time.perf_counter() - t0) * 1000))
    finally:
        try:
            sock.close()
        except OSError:
            pass


def probe_internet_rtt(hosts: Sequence[str] | None = None) -> int | None:
    """
    One composite probe: ICMP to next rotating host, then TCP to Cloudflare:443.
    """
    global _icmp_index
    hlist: Sequence[str] = hosts if hosts is not None else _PING_HOSTS_ICMP
    if hlist:
        i = _icmp_index % len(hlist)
        _icmp_index += 1
        host = hlist[i]
        ms = icmp_ping_ms(host)
        if ms is not None:
            return ms
    return tcp_connect_rtt_ms(_TCP_HOST, _TCP_PORT)


def smooth_rtt_ema(new_ms: int | None, prev_ema: float | None, alpha: float = 0.35) -> float | None:
    """EMA when we have a value; reset sensibly after outages."""
    if new_ms is None:
        return prev_ema
    v = float(new_ms)
    if prev_ema is None:
        return v
    return alpha * v + (1.0 - alpha) * prev_ema


def format_rate_bps(bps: float) -> str:
    """Short human string for B/s, KB/s, or MB/s."""
    bps = max(0.0, float(bps))
    if bps < 1024.0:
        return f"{bps:.0f}B/s"
    if bps < 1024.0 * 1024.0:
        return f"{bps / 1024.0:.1f}K/s"
    return f"{bps / 1024.0 / 1024.0:.1f}M/s"


class ThroughputSampler:
    """
    Deltas of psutil `net_io_counters` (all interfaces) → bytes per second up/down.
    """

    def __init__(self) -> None:
        self._last: object | None = None
        self._last_t: float | None = None

    def sample(self) -> tuple[float, float]:
        now = time.monotonic()
        try:
            cur = psutil.net_io_counters()
        except Exception:
            return 0.0, 0.0
        if self._last is None:
            self._last = cur
            self._last_t = now
            return 0.0, 0.0
        dt = now - (self._last_t or now)
        if dt < 0.05 or dt > 10.0:
            self._last = cur
            self._last_t = now
            return 0.0, 0.0
        d_sent = int(cur.bytes_sent) - int(self._last.bytes_sent)
        d_recv = int(cur.bytes_recv) - int(self._last.bytes_recv)
        if d_sent < 0 or d_recv < 0:
            self._last = cur
            self._last_t = now
            return 0.0, 0.0
        self._last = cur
        self._last_t = now
        up = d_sent / dt
        down = d_recv / dt
        return up, down
