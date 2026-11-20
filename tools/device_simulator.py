#!/usr/bin/env python3
"""GARDEKALINGA device simulator (BUILD_PROMPT C-8).

Signs every request exactly like the firmware (HMAC-SHA256 over method, path,
timestamp, nonce and body hash) and behaves like Box B:

  * 30-minute readings with drying / wetting soil and optional faulty probes
  * 3-second polls; executes start / stop / read_now with realistic interlock
    timing (valve 500 ms before pump, pump off 100 ms before valve) and acks them
  * acts on the server's decision after each reading
  * offline periods: readings and events go to a buffer, uploaded with /sync
  * power transitions at 11.6 V / 12.8 V and reboots with reset reasons

Examples
  # live, real time (poll every 3 s, reading every 30 min):
  python tools/device_simulator.py --url http://localhost:5000 --device gk-node-01 --secret <hex>

  # rehearse TC4: 24 simulated hours of readings in about a minute, then report
  python tools/device_simulator.py --url ... --secret ... backfill --hours 24

  # rehearse TC10: 2 h offline (fail-safe waters from its own readings), then sync
  python tools/device_simulator.py --url ... --secret ... offline --hours 2

  # faulty probe S3, and a power failover during the run
  python tools/device_simulator.py --url ... --secret ... --fault S3 live --minutes 10 --failover
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import random
import secrets
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

PROBES = ("S1", "S2", "S3")
CAL = {"adc_dry": 3000, "adc_sat": 1300, "vwc_dry": 5.0, "vwc_sat": 45.0}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def raw_from_vwc(v: float) -> int:
    frac = (v - CAL["vwc_dry"]) / (CAL["vwc_sat"] - CAL["vwc_dry"])
    return int(round(CAL["adc_dry"] - frac * (CAL["adc_dry"] - CAL["adc_sat"])))


@dataclass
class Node:
    url: str
    device: str
    secret: str
    faults: set = field(default_factory=set)
    soil: dict = field(default_factory=lambda: {"S1": 33.0, "S2": 31.0, "S3": 34.5})
    source: str = "adapter"
    supply_v: float = 12.02
    settings_version: int = 0
    max_s: int = 180
    online: bool = True
    buffer_readings: list = field(default_factory=list)
    buffer_events: list = field(default_factory=list)
    watering: dict | None = None
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=6.0))
    stats: dict = field(default_factory=lambda: {"readings": 0, "commands": 0, "latency": []})

    # ------------------------------------------------------------- signing
    def _headers(self, method: str, path: str, body: bytes) -> dict:
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        msg = "\n".join([method, path, ts, nonce, hashlib.sha256(body).hexdigest()]).encode()
        sig = hmac.new(bytes.fromhex(self.secret), msg, hashlib.sha256).hexdigest()
        return {"X-GK-Device": self.device, "X-GK-Timestamp": ts, "X-GK-Nonce": nonce, "X-GK-Signature": sig,
                "Content-Type": "application/json"}

    def request(self, method: str, path: str, payload=None):
        if not self.online:
            raise httpx.ConnectError("simulated: offline")
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        r = self.client.request(method, self.url + path, content=body or None, headers=self._headers(method, path, body))
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:200]}")
        return r.json()

    # ------------------------------------------------------------- physics
    def step_soil(self, at: datetime, minutes: float = 30) -> None:
        hour = (at.astimezone(timezone(timedelta(hours=8))).hour + 0.5) % 24
        sun = max(0.0, math.sin((hour - 6) / 12 * math.pi))
        for p in PROBES:
            dry = (0.1 + 0.6 * sun) * (minutes / 30) * {"S1": 1.0, "S2": 1.1, "S3": 0.93}[p]
            self.soil[p] = max(9.0, self.soil[p] - dry * random.uniform(0.8, 1.2))

    def reading(self, at: datetime, mode: str = "online") -> dict:
        probes = []
        good = []
        for p in PROBES:
            if p in self.faults:
                probes.append({"id": p, "raw": random.choice([31, 4095]), "vwc": None, "fault": True})
            else:
                v = self.soil[p] + random.uniform(-0.2, 0.2)
                probes.append({"id": p, "raw": raw_from_vwc(v), "vwc": round(v, 1), "fault": False})
                good.append(v)
        return {
            "reading_uuid": str(uuid.uuid4()),
            "recorded_at": iso(at),
            "probes": probes,
            "spatial_mean_vwc": round(sum(good) / len(good), 1) if good else None,
            "active_probe_count": len(good),
            "supply_v": round(self.supply_v + random.uniform(-0.03, 0.03), 2),
            "power_source": self.source,
            "control_mode": mode if good else "sensor_fault",
            "settings_version": self.settings_version,
            "fw": "1.0.0-sim",
            "uptime_s": int(time.monotonic()),
            "rssi": random.randint(-75, -55),
        }

    # ------------------------------------------------------------- actions
    def water(self, seconds: int, trigger: str, at: datetime, decision_id=None, command_id=None, reason="completed") -> dict:
        run = min(seconds, self.max_s)
        interlock = 500 + random.randint(-5, 6)
        gap = 100 + random.randint(-3, 4)
        pump_on = at + timedelta(milliseconds=interlock)
        pump_off = pump_on + timedelta(seconds=run)
        if seconds >= self.max_s:
            reason = "max_cutoff"
        for p in PROBES:
            self.soil[p] = min(46.0, self.soil[p] + 0.047 * run)
        print(f"  {iso(at)} WATER {trigger} {run}s interlock={interlock}ms gap={gap}ms ({reason})")
        return {"uuid": str(uuid.uuid4()), "type": "actuation", "trigger_source": trigger, "decision_id": decision_id,
                "command_id": command_id, "valve_open_at": iso(at), "pump_on_at": iso(pump_on), "pump_off_at": iso(pump_off),
                "valve_closed_at": iso(pump_off + timedelta(milliseconds=gap)), "interlock_ms": interlock, "close_gap_ms": gap,
                "duration_s": run, "ended_reason": reason}

    def send_event(self, ev: dict) -> None:
        try:
            self.request("POST", "/api/device/v1/events", ev)
        except Exception:
            self.buffer_events.append(ev)

    def post_reading(self, at: datetime, live: bool = True) -> None:
        body = self.reading(at, "online" if self.online else "offline_failsafe")
        for _attempt in range(3):  # 1 try + 2 retries, then fail-safe
            try:
                resp = self.request("POST", "/api/device/v1/readings", body)
                self.stats["readings"] += 1
                if resp.get("settings"):
                    self.settings_version = resp["settings"]["v"]
                    self.max_s = resp["settings"]["max"]
                d = resp.get("decision") or {}
                print(f"  {body['recorded_at']} reading mean={body['spatial_mean_vwc']} -> {d.get('action')} ({d.get('reason')})")
                if d.get("action") == "water":
                    self.send_event(self.water(d.get("duration_s", self.max_s), "auto", at + timedelta(seconds=2), decision_id=d.get("id")))
                return
            except Exception as e:  # noqa: BLE001
                last = e
                if live:
                    time.sleep(0.2)
        print(f"  {body['recorded_at']} POST failed twice after retry ({last}); offline fail-safe")
        body["control_mode"] = "offline_failsafe" if body["active_probe_count"] else "sensor_fault"
        self.buffer_readings.append(body)
        good = [p["vwc"] for p in body["probes"] if not p["fault"]]
        if good and (sum(good) / len(good) < 30 or min(good) < 22):
            self.buffer_events.append(self.water(self.max_s, "offline_failsafe", at + timedelta(seconds=3)))

    def sync(self) -> None:
        while self.buffer_readings or self.buffer_events:
            rs, es = self.buffer_readings[:24], self.buffer_events[:40]
            resp = self.request("POST", "/api/device/v1/sync", {"readings": rs, "events": es})
            print(f"  sync: {resp['accepted']} (duplicates {resp['duplicates']})")
            del self.buffer_readings[: len(rs)]
            del self.buffer_events[: len(es)]

    def poll(self) -> None:
        w = self.watering
        rem = max(0, int(w["end"] - time.time())) if w else 0
        q = (f"/api/device/v1/poll?p={int(bool(w))}&v={int(bool(w))}&src={self.source}&sv={self.supply_v:.2f}"
             f"&m=online&w={2 if w else 0}&rem={rem}&s={self.settings_version}")
        t0 = time.time()
        resp = self.request("GET", q)
        for c in resp.get("cmd", []):
            self.stats["commands"] += 1
            if c["op"] == "start":
                if w:
                    self.request("POST", f"/api/device/v1/commands/{c['id']}/ack", {"status": "rejected", "reason": "already_watering"})
                    continue
                run = min(c.get("d", 60), self.max_s)
                self.watering = {"start": datetime.now(timezone.utc), "end": time.time() + run + 0.5, "cmd": c["id"], "run": run}
                self.request("POST", f"/api/device/v1/commands/{c['id']}/ack", {"status": "executed", "at": iso(datetime.now(timezone.utc))})
                self.stats["latency"].append(round(time.time() - t0, 2))
                print(f"  command {c['id']} start {run}s acknowledged")
            elif c["op"] == "stop":
                if self.watering:
                    ev = self.water(int(time.time() - self.watering["end"] + self.watering["run"]), "manual", self.watering["start"],
                                    command_id=self.watering["cmd"], reason="manual_stop")
                    self.send_event(ev)
                    self.watering = None
                self.request("POST", f"/api/device/v1/commands/{c['id']}/ack", {"status": "executed"})
                print(f"  command {c['id']} stop")
            elif c["op"] == "read_now":
                rd = self.reading(datetime.now(timezone.utc))
                self.send_event({"uuid": str(uuid.uuid4()), "type": "read_now", "data": {"probes": rd["probes"]}})
                self.request("POST", f"/api/device/v1/commands/{c['id']}/ack", {"status": "executed"})
        if self.watering and time.time() >= self.watering["end"]:
            self.send_event(self.water(self.watering["run"], "manual", self.watering["start"], command_id=self.watering["cmd"]))
            self.watering = None

    def power(self, to: str) -> None:
        frm, self.source = self.source, to
        self.supply_v = 11.58 if to == "adapter" else 12.86
        self.send_event({"uuid": str(uuid.uuid4()), "type": "power_transition", "occurred_at": iso(datetime.now(timezone.utc)),
                         "from": frm, "to": to, "supply_v": self.supply_v})
        self.supply_v = 12.02 if to == "adapter" else 13.3
        print(f"  power {frm} -> {to}")

    def boot(self, reason: str = "POWERON") -> None:
        self.send_event({"uuid": str(uuid.uuid4()), "type": "boot", "occurred_at": iso(datetime.now(timezone.utc)),
                         "reset_reason": reason, "fw": "1.0.0-sim"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5000")
    ap.add_argument("--device", default="gk-node-01")
    ap.add_argument("--secret", required=True, help="64 hex characters from `make register-device`")
    ap.add_argument("--fault", action="append", default=[], choices=PROBES, help="mark a probe faulty (repeatable)")
    ap.add_argument("--seed", type=int, default=7)
    sub = ap.add_subparsers(dest="mode")
    live = sub.add_parser("live", help="real-time node: 3 s polls, 30 min readings (default)")
    live.add_argument("--minutes", type=float, default=0, help="stop after N minutes (0 = forever)")
    live.add_argument("--failover", action="store_true", help="switch to the wall socket and back during the run")
    bf = sub.add_parser("backfill", help="post N hours of 30-minute readings quickly (TC4 rehearsal)")
    bf.add_argument("--hours", type=float, default=24)
    off = sub.add_parser("offline", help="N hours offline with fail-safe, then sync (TC10 rehearsal)")
    off.add_argument("--hours", type=float, default=2)
    args = ap.parse_args()
    random.seed(args.seed)

    node = Node(args.url.rstrip("/"), args.device, args.secret, faults=set(args.fault))
    node.boot()
    mode = args.mode or "live"

    if mode == "backfill":
        start = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        start = start.replace(minute=0 if start.minute < 30 else 30, second=0, microsecond=0)
        t = start
        while t <= datetime.now(timezone.utc):
            node.step_soil(t)
            node.post_reading(t, live=False)
            t += timedelta(minutes=30)
        print(f"posted {node.stats['readings']} readings for {args.hours} h")
        return 0

    if mode == "offline":
        node.online = False
        start = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        t = start
        while t <= datetime.now(timezone.utc):
            node.step_soil(t)
            node.post_reading(t, live=False)
            t += timedelta(minutes=30)
        print(f"buffered {len(node.buffer_readings)} readings and {len(node.buffer_events)} events while offline")
        node.online = True
        node.sync()
        node.sync()  # a second sync must store nothing new (idempotent)
        return 0

    # live
    end = time.time() + args.minutes * 60 if args.minutes else float("inf")
    next_reading = time.time()
    flipped = False
    while time.time() < end:
        try:
            node.poll()
            if node.buffer_readings or node.buffer_events:
                node.sync()
        except Exception as e:  # noqa: BLE001
            print(f"  poll failed: {e}")
        if time.time() >= next_reading:
            node.step_soil(datetime.now(timezone.utc))
            node.post_reading(datetime.now(timezone.utc))
            next_reading = time.time() + 1800
        if getattr(args, "failover", False) and not flipped and args.minutes and time.time() > end - args.minutes * 30:
            node.power("adapter" if node.source == "solar" else "solar")
            flipped = True
        time.sleep(3)
    print(json.dumps(node.stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
