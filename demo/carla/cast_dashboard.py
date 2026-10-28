#!/usr/bin/env python3
"""The proof-cast dashboard of the CARLA island demo (docs/design/carla-island-demo.md, unit C8).

  cast_dashboard.py [--xosc <scenario>] [--osm <lanelet2_map.osm>] [--log <events.jsonl>]
                    [--carla-host 127.0.0.1] [--carla-port 2000] [--no-camera]

One 1920x1080 window, meant for a TurboVNC display recorded with ffmpeg
(demo/carla/cast.sh): what an act shows, readable at 1080p, on one clock.

  banner        the state in one line, large: AUTONOMOUS / OUT OF ODD /
                TAKEOVER REQUESTED (with the window's countdown) / DRIVER IN
                CONTROL / ISLAND MRM / STOPPED; the host's wall clock and the
                simulation time (/clock) at its right
  chase view    a CARLA RGB camera behind the hero (a client of the running
                CARLA, attached to the vehicle whose role_name is hero/ego)
  ODD           odd_monitor's /demo/odd/exit and /demo/odd/reason, speed
  takeover      /system/operation_mode/availability (autonomous),
                /api/operation_mode/state, /vehicle/status/control_mode,
                /system/takeover_request/state
  island        /system/fail_safe/mrm_state and the board's LED, mirrored
                from it with section 3.2's mapping (the host has no camera
                for the board)
  map           the Town01 straight from the Lanelet2 map, the scenario's ODD
                polygon (IslandOddPolygon), the ego's track and pose, a
                marker where the ODD exit fired and where the ego stopped
  events        each transition, stamped with wall time and simulation time

Every stamp on screen is the host's wall clock (time.time(), local) or the
simulation's /clock; the event log (--log) keeps both per transition, which
is how cast.sh finds the frames for its stills.

Environment: the L3 host environment (rmw_zenoh_cpp, domain 10, the
overlay's messages; demo/l3/container/bin/l3-env) and DISPLAY. The carla
client library (0.9.16, ~/.local) is needed only for the chase view.
"""
import argparse
import json
import math
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET

from PyQt5 import QtCore, QtGui, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "l3", "takeover_demo"))
from takeover_demo.odd_scenario import read_scenario_odd, parse_polygon  # noqa: E402

W, H = 1920, 1080
MRM_STATE = {0: "UNKNOWN", 1: "NORMAL", 2: "MRM_OPERATING", 3: "MRM_SUCCEEDED", 4: "MRM_FAILED"}
MRM_BEHAVIOR = {0: "UNKNOWN", 1: "NONE", 2: "EMERGENCY_STOP", 3: "COMFORTABLE_STOP", 4: "PULL_OVER"}
TOR_STATE = {0: "NOT_AVAILABLE", 1: "AVAILABLE", 2: "OPERATING"}
OP_MODE = {0: "UNKNOWN", 1: "STOP", 2: "AUTONOMOUS", 3: "LOCAL", 4: "REMOTE"}
CTRL_MODE = {0: "NO_COMMAND", 1: "AUTONOMOUS", 2: "AUTONOMOUS_STEER_ONLY", 3: "AUTONOMOUS_VELOCITY_ONLY",
             4: "MANUAL", 5: "DISENGAGED", 6: "NOT_READY"}
WINDOW_S = 10.0  # takeover_request_timeout (mrm_handler.param.yaml)

C = dict(bg="#101418", panel="#1b2128", ink="#f2f4f6", dim="#9aa5b1", green="#2fbf60", amber="#f2a900",
         red="#e5322d", blue="#3d8bfd", magenta="#d63fd0", grey="#5b6670", road="#3a434d", lane="#6b7682",
         odd="#2fbf60")


def wall_text(t):
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


class State:
    """Everything the window draws; written by the ROS and CARLA threads."""

    def __init__(self, log_path):
        self.lock = threading.Lock()
        self.x = self.y = self.v = None
        self.track = []
        self.sim = None
        self.avail = None          # autonomous available (bool)
        self.op_mode = None
        self.ctrl = None
        self.tor = None
        self.tor_on_t = None
        self.mrm = None            # (state, behavior)
        self.odd_exit = None
        self.odd_reason = ""
        self.odd_mark = None       # (x, y) where the exit fired
        self.stop_mark = None
        self.moved = False
        self.events = []
        self.cam = None            # (QImage, frame, carla seconds)
        self.cam_status = "connecting to CARLA ..."
        self.cam_actor = None      # destroyed at exit, so the hero carries no stray sensor
        self.log = open(log_path, "a", buffering=1) if log_path else None

    def event(self, text, colour, **extra):
        t = time.time()
        e = dict(wall=t, sim=self.sim, text=text, colour=colour, x=self.x, y=self.y, **extra)
        self.events.append(e)
        if self.log:
            self.log.write(json.dumps(e) + "\n")


# ------------------------------------------------------------------ ROS ----
def ros_thread(st):
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from autoware_adapi_v1_msgs.msg import MrmState, OperationModeState
    from autoware_vehicle_msgs.msg import ControlModeReport
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import Bool, String
    from tier4_system_msgs.msg import MrmBehaviorStatus, OperationModeAvailability

    rclpy.init()
    node = rclpy.create_node("cast_dashboard")
    q = QoSProfile(depth=5)
    ql = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    qb = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)

    def odom(m):
        with st.lock:
            st.x, st.y = m.pose.pose.position.x, m.pose.pose.position.y
            st.v = m.twist.twist.linear.x
            if not st.track or math.hypot(st.x - st.track[-1][0], st.y - st.track[-1][1]) > 0.5:
                st.track.append((st.x, st.y))
                del st.track[:-4000]
            if abs(st.v) > 1.0:
                st.moved, st.stop_mark = True, None
            elif st.moved and abs(st.v) < 0.05 and st.stop_mark is None:
                st.stop_mark = (st.x, st.y)
                st.event(f"STANDSTILL at x {st.x:.1f}", C["red"])

    def clock(m):
        with st.lock:
            st.sim = m.clock.sec + m.clock.nanosec * 1e-9

    def avail(m):
        with st.lock:
            if st.avail is not None and m.autonomous != st.avail:
                st.event(f"autonomous available: {'yes' if m.autonomous else 'NO'}",
                         C["green"] if m.autonomous else C["amber"])
            st.avail = m.autonomous

    def opmode(m):
        with st.lock:
            if m.mode != st.op_mode and st.op_mode is not None:
                st.event(f"operation mode {OP_MODE.get(m.mode, m.mode)}", C["dim"])
            st.op_mode = m.mode

    def ctrl(m):
        with st.lock:
            if m.mode != st.ctrl and st.ctrl is not None:
                st.event(f"control mode {CTRL_MODE.get(m.mode, m.mode)}"
                         + (": THE DRIVER TOOK OVER" if m.mode == 4 else ""),
                         C["blue"] if m.mode == 4 else C["dim"])
            st.ctrl = m.mode

    def tor(m):
        with st.lock:
            if m.state != st.tor:
                if m.state == 2:
                    st.tor_on_t = time.time()
                    st.event("TAKEOVER REQUESTED (/system/takeover_request/state OPERATING)", C["amber"])
                elif st.tor == 2:
                    st.event(f"takeover request off ({TOR_STATE.get(m.state, m.state)})", C["dim"])
                    st.tor_on_t = None
            st.tor = m.state

    def mrm(m):
        with st.lock:
            v = (m.state, m.behavior)
            if v != st.mrm and st.mrm is not None:
                col = C["green"] if m.state == 1 else C["red"] if (m.state == 3 or m.behavior == 2) else C["amber"]
                st.event(f"island MRM: {MRM_STATE.get(m.state, m.state)} / {MRM_BEHAVIOR.get(m.behavior, m.behavior)}", col)
            st.mrm = v

    def odd_exit(m):
        with st.lock:
            if m.data and not st.odd_exit:
                st.odd_mark = (st.x, st.y)
                st.event(f"ODD EXIT: {st.odd_reason}" if st.odd_reason not in ("", "in ODD") else "ODD EXIT",
                         C["amber"])
            st.odd_exit = m.data
            if not m.data:
                st.odd_mark = None if st.odd_reason == "in ODD" else st.odd_mark

    def odd_reason(m):
        with st.lock:
            st.odd_reason = m.data

    node.create_subscription(Odometry, "/localization/kinematic_state", odom, q)
    node.create_subscription(Clock, "/clock", clock, qb)
    node.create_subscription(OperationModeAvailability, "/system/operation_mode/availability", avail, q)
    node.create_subscription(OperationModeState, "/api/operation_mode/state", opmode, ql)
    node.create_subscription(ControlModeReport, "/vehicle/status/control_mode", ctrl, q)
    node.create_subscription(MrmBehaviorStatus, "/system/takeover_request/state", tor, q)
    node.create_subscription(MrmState, "/system/fail_safe/mrm_state", mrm, q)
    node.create_subscription(String, "/demo/odd/reason", odd_reason, q)
    node.create_subscription(Bool, "/demo/odd/exit", odd_exit, q)
    rclpy.spin(node)


# ---------------------------------------------------------------- CARLA ----
def carla_thread(st, host, port, size):
    try:
        import carla
        import numpy as np
    except ImportError as e:
        st.cam_status = f"no chase view: {e}"
        return
    client = carla.Client(host, port)
    client.set_timeout(5.0)
    cam = hero = None
    world_id = None
    while True:
        try:
            world = client.get_world()
            if world.id != world_id:
                cam, hero, world_id = None, None, world.id
            if hero is None or not hero.is_alive:
                if cam is not None:
                    try:
                        cam.destroy()
                    except RuntimeError:
                        pass
                    cam = None
                vs = [a for a in world.get_actors().filter("vehicle.*")
                      if a.attributes.get("role_name") in ("hero", "ego")]
                hero = vs[0] if vs else None
                st.cam_status = "waiting for the hero ..." if hero is None else "hero found"
            if hero is not None and cam is None:
                bp = world.get_blueprint_library().find("sensor.camera.rgb")
                bp.set_attribute("image_size_x", str(size[0]))
                bp.set_attribute("image_size_y", str(size[1]))
                bp.set_attribute("fov", "90")
                tf = carla.Transform(carla.Location(x=-8.0, z=3.4), carla.Rotation(pitch=-13.0))
                cam = world.spawn_actor(bp, tf, attach_to=hero)

                def on_image(img, st=st):
                    a = np.frombuffer(img.raw_data, dtype=np.uint8).reshape(img.height, img.width, 4)
                    rgb = np.ascontiguousarray(a[:, :, 2::-1])
                    qi = QtGui.QImage(rgb.data, img.width, img.height, 3 * img.width,
                                      QtGui.QImage.Format_RGB888).copy()
                    with st.lock:
                        st.cam = (qi, img.frame, img.timestamp)
                cam.listen(on_image)
                st.cam_actor = cam
                st.cam_status = f"hero id {hero.id}"
        except RuntimeError as e:
            st.cam_status = f"CARLA: {str(e)[:60]}"
            cam = hero = None
            world_id = None
        time.sleep(1.0)


# ------------------------------------------------------------------ map ----
def load_road(osm, bbox):
    """Lanelet2 ways (local_x/local_y) inside bbox, as polylines."""
    if not osm or not os.path.exists(osm):
        return []
    root = ET.parse(osm).getroot()
    nodes = {}
    for n in root.iter("node"):
        tags = {t.get("k"): t.get("v") for t in n.iter("tag")}
        if "local_x" in tags:
            nodes[n.get("id")] = (float(tags["local_x"]), float(tags["local_y"]))
    lines = []
    x0, x1, y0, y1 = bbox
    for w in root.iter("way"):
        pts = [nodes[r.get("ref")] for r in w.iter("nd") if r.get("ref") in nodes]
        if any(x0 - 20 <= x <= x1 + 20 and y0 - 20 <= y <= y1 + 20 for x, y in pts):
            lines.append(pts)
    return lines


# --------------------------------------------------------------- window ----
class Dash(QtWidgets.QWidget):
    def __init__(self, st, poly, max_kmh, road, bbox, scenario):
        super().__init__()
        self.st, self.poly, self.max_kmh, self.road, self.bbox = st, poly, max_kmh, road, bbox
        self.scenario = scenario
        self.setWindowTitle("island cast")
        self.setFixedSize(W, H)
        self.f = {k: QtGui.QFont("DejaVu Sans", s, QtGui.QFont.Bold if b else QtGui.QFont.Normal)
                  for k, (s, b) in dict(banner=(40, True), clock=(24, True), title=(17, True), big=(28, True),
                                        mid=(21, False), small=(15, False)).items()}
        for f in self.f.values():
            f.setPixelSize(round(f.pointSize() * 1.33))
        self.f["mono"] = QtGui.QFont("DejaVu Sans Mono")
        self.f["mono"].setPixelSize(22)
        t = QtCore.QTimer(self)
        t.timeout.connect(self.update)
        t.start(33)

    # -- helpers
    def text(self, p, rect, s, font, colour=C["ink"], flags=QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter):
        p.setFont(self.f[font])
        p.setPen(QtGui.QColor(colour))
        p.drawText(QtCore.QRectF(*rect), flags, s)

    def panel(self, p, rect, title):
        p.fillRect(QtCore.QRectF(*rect), QtGui.QColor(C["panel"]))
        self.text(p, (rect[0] + 16, rect[1] + 6, rect[2] - 32, 28), title, "title", C["dim"])

    def blink(self, hz):
        return (time.time() * hz) % 1.0 < 0.5

    def led(self, s):
        """Section 3.2: (colour, blink Hz or 0, words)."""
        if s.mrm is None:
            return C["blue"], 1.0, "blue blinking: waiting"
        state, beh = s.mrm
        if state == 1:
            return (C["amber"], 2.5, "amber blinking: take over") if s.tor == 2 else \
                (C["green"], 0, "green: the island watches")
        if state == 2:
            return (C["red"], 2.5, "red blinking: emergency stop") if beh == 2 else \
                (C["amber"], 0, "amber: stopping gently")
        if state == 3:
            return C["red"], 0, "red: stopped, safe"
        if state == 4:
            return C["magenta"], 2.5, "magenta blinking: stop failed"
        return C["grey"], 0, "-"

    def banner(self, s):
        if s.mrm and s.mrm[0] == 3:
            return C["red"], "STOPPED SAFELY - ISLAND MRM SUCCEEDED", False
        if s.mrm and s.mrm[0] == 2:
            what = "EMERGENCY STOP" if s.mrm[1] == 2 else "COMFORTABLE STOP" if s.mrm[1] == 3 else MRM_BEHAVIOR.get(s.mrm[1])
            return (C["red"] if s.mrm[1] == 2 else C["amber"]), f"ISLAND MRM: {what}", s.mrm[1] == 2
        if s.tor == 2:
            left = WINDOW_S - (time.time() - s.tor_on_t) if s.tor_on_t else WINDOW_S
            return C["amber"], f"TAKEOVER REQUESTED - {max(0.0, left):4.1f} s left", True
        if s.ctrl == 4:
            return C["blue"], "DRIVER IN CONTROL (MANUAL) - NO MRM", False
        if s.odd_exit:
            return C["amber"], "OUT OF ODD", False
        if s.op_mode == 2:
            return C["green"], "AUTONOMOUS - INSIDE THE ODD", False
        return C["grey"], f"WAITING - operation mode {OP_MODE.get(s.op_mode, '-')}", False

    # -- paint
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(C["bg"]))
        with self.st.lock:
            s = self.st
            now = time.time()
            # banner
            col, words, blinks = self.banner(s)
            bc = QtGui.QColor(col)
            if blinks and not self.blink(2.5):
                bc = bc.darker(260)
            p.fillRect(0, 0, W, 96, bc)
            self.text(p, (24, 0, 1400, 96), words, "banner", "#0b0d10" if col != C["grey"] else C["ink"])
            self.text(p, (1420, 6, 480, 44), f"wall {wall_text(now)}", "clock", "#0b0d10" if col != C["grey"] else C["ink"],
                      QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.text(p, (1420, 48, 480, 40), "sim  " + (f"{s.sim:10.2f} s" if s.sim is not None else "-"), "clock",
                      "#0b0d10" if col != C["grey"] else C["ink"], QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # chase view
            cx, cy, cw, ch = 0, 104, 1066, 600
            p.fillRect(cx, cy, cw, ch, QtGui.QColor("#000000"))
            if s.cam:
                p.drawImage(QtCore.QRect(cx, cy, cw, ch), s.cam[0])
                tag = f"CARLA chase view - frame {s.cam[1]}, CARLA t {s.cam[2]:.2f} s"
            else:
                tag = f"CARLA chase view - {s.cam_status}"
            p.fillRect(cx, cy + ch - 34, cw, 34, QtGui.QColor(0, 0, 0, 150))
            self.text(p, (cx + 12, cy + ch - 34, cw - 24, 34), tag, "small", C["ink"])
            # right column
            rx, rw = 1074, W - 1074 - 8
            self.panel(p, (rx, 104, rw, 190), "ODD  (odd_monitor, declared by the scenario)")
            if s.odd_exit:
                self.text(p, (rx + 16, 140, rw - 32, 50), "OUT OF ODD", "big", C["amber"])
                self.text(p, (rx + 16, 190, rw - 32, 40), s.odd_reason, "mid", C["ink"])
            else:
                self.text(p, (rx + 16, 140, rw - 32, 50), "IN ODD" if s.odd_exit is not None else "-", "big",
                          C["green"] if s.odd_exit is False else C["dim"])
                self.text(p, (rx + 16, 190, rw - 32, 40),
                          f"polygon {len(self.poly)} points, |v| <= {self.max_kmh:.0f} km/h", "mid", C["dim"])
            self.text(p, (rx + 16, 236, rw - 32, 44),
                      "speed " + (f"{abs(s.v) * 3.6:5.1f} km/h" if s.v is not None else "-")
                      + ("   x " + f"{s.x:6.1f}" if s.x is not None else ""), "mid", C["ink"])

            self.panel(p, (rx, 302, rw, 196), "TAKEOVER REQUEST  (HPC side -> island)")
            rows = [("autonomous available", "-" if s.avail is None else ("yes" if s.avail else "NO"),
                     C["green"] if s.avail else C["amber"] if s.avail is False else C["dim"]),
                    ("operation mode", OP_MODE.get(s.op_mode, "-"), C["ink"]),
                    ("control mode", CTRL_MODE.get(s.ctrl, "-"), C["blue"] if s.ctrl == 4 else C["ink"]),
                    ("/system/takeover_request/state", TOR_STATE.get(s.tor, "-"),
                     C["amber"] if s.tor == 2 else C["ink"])]
            for i, (k, v, c) in enumerate(rows):
                self.text(p, (rx + 16, 336 + i * 34, 470, 34), k, "mid", C["dim"])
                self.text(p, (rx + 480, 336 + i * 34, rw - 496, 34), v, "mid", c)
            if s.mrm and s.mrm[0] in (2, 3):
                # the island's MRM acts below Autoware's operation mode: the
                # modes above still read AUTONOMOUS, which is not the driver
                self.text(p, (rx + 16, 470, rw - 32, 26),
                          "island MRM overrides control; Autoware's modes stay AUTONOMOUS", "small", C["amber"])

            self.panel(p, (rx, 506, rw, 198), "SAFETY ISLAND  (NXP S32K344, /system/fail_safe/mrm_state)")
            lc, hz, lw = self.led(s)
            on = hz == 0 or self.blink(hz)
            p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 3))
            p.setBrush(QtGui.QColor(lc) if on else QtGui.QColor(lc).darker(400))
            p.drawEllipse(QtCore.QPointF(rx + 86, 616), 54, 54)
            st_txt = "-" if s.mrm is None else MRM_STATE.get(s.mrm[0], s.mrm[0])
            bh_txt = "" if s.mrm is None else MRM_BEHAVIOR.get(s.mrm[1], s.mrm[1])
            self.text(p, (rx + 168, 540, rw - 184, 50), st_txt, "big",
                      C["green"] if st_txt == "NORMAL" else C["red"] if st_txt in ("MRM_SUCCEEDED", "MRM_FAILED") else C["amber"])
            self.text(p, (rx + 168, 590, rw - 184, 40), f"behavior {bh_txt}", "mid", C["ink"])
            self.text(p, (rx + 168, 636, rw - 184, 40), f"LED (mirrored): {lw}", "mid", C["dim"])
            # map strip
            self.draw_map(p, s, (8, 712, W - 16, 200))
            # events
            p.fillRect(8, 920, W - 16, 152, QtGui.QColor(C["panel"]))
            self.text(p, (24, 922, 900, 26), "EVENTS  (wall clock | simulation time)", "title", C["dim"])
            for i, e in enumerate(s.events[-4:]):
                simt = f"{e['sim']:8.2f}" if e.get("sim") is not None else "       -"
                self.text(p, (24, 950 + i * 30, W - 48, 30), f"{wall_text(e['wall'])} | {simt} s   {e['text']}",
                          "mono", e["colour"])
        p.end()

    def draw_map(self, p, s, rect):
        x, y, w, h = rect
        p.fillRect(QtCore.QRectF(x, y, w, h), QtGui.QColor(C["panel"]))
        p.save()
        p.setClipRect(QtCore.QRectF(x, y, w, h))
        x0, x1, y0, y1 = self.bbox
        k = min((w - 40) / (x1 - x0), (h - 60) / (y1 - y0))
        ox = x + 20 + ((w - 40) - k * (x1 - x0)) / 2
        oy = y + 36 + ((h - 56) - k * (y1 - y0)) / 2

        def P(mx, my):
            return QtCore.QPointF(ox + (mx - x0) * k, oy + (y1 - my) * k)
        p.setPen(QtGui.QPen(QtGui.QColor(C["lane"]), 1.5))
        for line in self.road:
            p.drawPolyline(QtGui.QPolygonF([P(*q) for q in line]))
        if self.poly:
            pc = QtGui.QColor(C["odd"])
            pc.setAlpha(60)
            p.setBrush(pc)
            p.setPen(QtGui.QPen(QtGui.QColor(C["odd"]), 3))
            p.drawPolygon(QtGui.QPolygonF([P(*q) for q in self.poly]))
            bx = min(q[0] for q in self.poly)
            top = min(P(*q).y() for q in self.poly)
            self.text(p, (P(bx, 0).x() + 8, top - 30, 600, 26), f"ODD: the scenario's polygon, west boundary x {bx:.0f}",
                      "small", C["odd"])
        if len(s.track) > 1:
            p.setPen(QtGui.QPen(QtGui.QColor(C["blue"]), 3))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPolyline(QtGui.QPolygonF([P(*q) for q in s.track]))
        if s.odd_mark and s.odd_mark[0] is not None:
            q = P(*s.odd_mark)
            p.setPen(QtGui.QPen(QtGui.QColor(C["amber"]), 5))
            p.drawLine(q + QtCore.QPointF(-14, -14), q + QtCore.QPointF(14, 14))
            p.drawLine(q + QtCore.QPointF(-14, 14), q + QtCore.QPointF(14, -14))
            # west of the cross, clear of the polygon's outline
            self.text(p, (q.x() - 320, q.y() + 14, 300, 26), f"ODD exit x {s.odd_mark[0]:.1f}", "small", C["amber"],
                      QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if s.stop_mark:
            q = P(*s.stop_mark)
            p.setPen(QtGui.QPen(QtGui.QColor(C["red"]), 4))
            p.setBrush(QtGui.QColor(C["red"]))
            p.drawRect(QtCore.QRectF(q.x() - 10, q.y() - 10, 20, 20))
            self.text(p, (q.x() - 150, q.y() + 16, 300, 26), f"stopped x {s.stop_mark[0]:.1f}", "small", C["red"],
                      QtCore.Qt.AlignCenter)
        if s.x is not None:
            q = P(s.x, s.y)
            p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 2))
            p.setBrush(QtGui.QColor(C["ink"]))
            p.drawEllipse(q, 10, 10)
            self.text(p, (q.x() - 60, q.y() - 34, 120, 22), "ego", "small", C["ink"], QtCore.Qt.AlignCenter)
        p.restore()
        p.fillRect(QtCore.QRectF(x, y, 1300, 32), QtGui.QColor(C["panel"]))
        self.text(p, (x + 16, y + 4, 1280, 26),
                  f"MAP  Town01, map frame, x {x0:.0f}..{x1:.0f} m (west <- -> east)   {os.path.basename(self.scenario or '')}",
                  "title", C["dim"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xosc", default=os.path.join(HERE, "scenarios", "town01_island_odd.xosc"))
    ap.add_argument("--osm", default=os.path.join(
        os.environ.get("CSB_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "carla-scenario-bridge")),
        "data/carla-autoware-bridge/Town01/lanelet2_map.osm"))
    ap.add_argument("--log", default=None)
    ap.add_argument("--carla-host", default="127.0.0.1")
    ap.add_argument("--carla-port", type=int, default=int(os.environ.get("CARLA_PORT", "2000")))
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--no-ros", action="store_true", help="layout check only")
    a = ap.parse_args()
    poly, kmh = [], 30.0
    try:
        pt, sk = read_scenario_odd(a.xosc)
        poly = parse_polygon(pt) if pt else []
        kmh = sk if sk is not None else kmh
    except (ValueError, OSError) as e:
        print(f"cast_dashboard: no ODD from {a.xosc}: {e}", file=sys.stderr)
    bbox = (110.0, 335.0, -140.0, -120.0)
    road = load_road(a.osm, bbox)
    st = State(a.log)
    app = QtWidgets.QApplication(sys.argv[:1])
    if not a.no_ros:
        threading.Thread(target=ros_thread, args=(st,), daemon=True).start()
    if not a.no_camera:
        threading.Thread(target=carla_thread, args=(st, a.carla_host, a.carla_port, (1066, 600)), daemon=True).start()
    else:
        st.cam_status = "off (--no-camera)"
    d = Dash(st, poly, kmh, road, bbox, a.xosc)
    d.move(0, 0)
    d.show()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    rc = app.exec_()
    if st.cam_actor is not None:
        try:
            st.cam_actor.stop()
            st.cam_actor.destroy()
        except RuntimeError:
            pass
    os._exit(rc)


if __name__ == "__main__":
    main()
