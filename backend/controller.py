"""Headless teleop / record / playback controller.

Modes:
    follow              master → slave teleop (default)
    record              follow + sampling joint_states into the active recording
    transition          smooth blend from current slave pose → action[0]
    playback            playing back an action (loop or once)
    return_to_follow    after a "once" playback: slow blend → live master pose

The control loop is a regular Python thread running at UPDATE_RATE Hz. The
FastAPI layer calls Controller.start_*/stop_* methods (RLock-protected) and
reads thread-safe state via Controller.snapshot().
"""
from __future__ import annotations

import logging
import math
import threading
import time
from copy import deepcopy
from typing import Optional

import serial
import serial.tools.list_ports

from .config import Config
from .models import Action, ControllerMode, PlayMode
from .pipermate import PiPER_MateAgilex
from .storage import ActionLibrary
from .u2can.DM_CAN import (
    Control_Type,
    DM_Motor_Type,
    Motor,
    MotorControl,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Port detection (daemon-friendly: no input(), env-var override)
# ---------------------------------------------------------------------------

def detect_ports(
    preferred_master: Optional[str] = None,
    preferred_slave: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Auto-detect master + slave serial ports.

    Master arm: CH340 (VID=0x1a86, PID=0x7523), the B601-DM driver board.
    Slave arm: HDSC CDC_Device (manufacturer == "HDSC" or product startswith "CDC").

    Multiple candidates → log warning, pick first. None → return None.
    Caller passes env-var overrides as `preferred_master`/`preferred_slave`.
    """
    ports = list(serial.tools.list_ports.comports())

    def fmt(p):
        vid = f"{p.vid:04x}" if p.vid else "----"
        pid = f"{p.pid:04x}" if p.pid else "----"
        return (f"{p.device:<18} {vid}:{pid}  mfr={p.manufacturer!r}  "
                f"product={p.product!r}")

    log.info("Enumerated %d serial port(s):", len(ports))
    for p in ports:
        log.info("  %s", fmt(p))

    master_candidates = [p for p in ports if p.vid == 0x1a86 and p.pid == 0x7523]
    slave_candidates = [
        p for p in ports
        if (p.manufacturer or "").upper() == "HDSC"
        or (p.product or "").upper().startswith("CDC")
    ]

    def pick(label: str, cands, preferred: Optional[str]) -> Optional[str]:
        if preferred:
            if any(c.device == preferred for c in cands):
                log.info("%s: using configured %s", label, preferred)
                return preferred
            log.warning("%s: configured port %s not in candidates; falling back to auto-detect",
                        label, preferred)
        if not cands:
            log.error("%s: no candidates found", label)
            return None
        if len(cands) > 1:
            log.warning("%s: %d candidates, picking first (%s)",
                        label, len(cands), cands[0].device)
        else:
            log.info("%s: auto-selected %s (%s)", label, cands[0].device, cands[0].product)
        return cands[0].device

    return (
        pick("master (B601-DM / CH340)", master_candidates, preferred_master),
        pick("slave (SO102 / HDSC CDC)", slave_candidates, preferred_slave),
    )


# ---------------------------------------------------------------------------
# Slave arm wrapper
# ---------------------------------------------------------------------------

class SlaveArm:
    def __init__(self, port: str, baudrate: int = 921600, name: str = "slave"):
        self.port = port
        self.baudrate = baudrate
        self.name = name
        self.serial_device: Optional[serial.Serial] = None
        self.motor_control: Optional[MotorControl] = None
        self.motors: list[Motor] = []

    def setup(self) -> None:
        self.serial_device = serial.Serial(self.port, self.baudrate, timeout=0.5)

        Motor1 = Motor(DM_Motor_Type.DM4340, 0x01, 0x11)
        Motor2 = Motor(DM_Motor_Type.DM4340, 0x02, 0x12)
        Motor3 = Motor(DM_Motor_Type.DM4340, 0x03, 0x13)
        Motor4 = Motor(DM_Motor_Type.DM4310, 0x04, 0x14)
        Motor5 = Motor(DM_Motor_Type.DM4310, 0x05, 0x15)
        Motor6 = Motor(DM_Motor_Type.DM4310, 0x06, 0x16)
        Motor7 = Motor(DM_Motor_Type.DM4310, 0x07, 0x17)

        self.motor_control = MotorControl(self.serial_device)
        for m in (Motor1, Motor2, Motor3, Motor4, Motor5, Motor6, Motor7):
            self.motor_control.addMotor(m)
        self.motors = [Motor1, Motor2, Motor3, Motor4, Motor5, Motor6, Motor7]

        for motor in self.motors:
            self.motor_control.disable(motor)
            if motor is not Motor7:
                self.motor_control.switchControlMode(motor, Control_Type.POS_VEL)
            else:
                self.motor_control.switchControlMode(motor, Control_Type.Torque_Pos)
            self.motor_control.enable(motor)
            time.sleep(0.001)

        log.info("[%s] initialized on %s", self.name, self.port)

    def send_joint_states(self, js: dict) -> None:
        self.motor_control.control_Pos_Vel(self.motors[0], js["joint1"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[1], js["joint2"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[2], js["joint3"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[3], js["joint4"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[4], js["joint5"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[5], js["joint6"], 15)
        time.sleep(0.0005)
        self.motor_control.control_pos_force(self.motors[6], js["gripper"], 2000, 350)

    def recover(self) -> None:
        """Re-handshake all motors after a single CAN/power line was reconnected.

        Sequence per motor: disable → switchControlMode → enable → refresh_motor_status.
        Idempotent. Caller must pause the controller first so no commands race.
        """
        if not self.motor_control or not self.motors:
            return
        log.warning("[%s] recover: re-enabling all motors", self.name)
        for motor in self.motors:
            try:
                self.motor_control.disable(motor)
                time.sleep(0.005)
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] disable id=%d failed: %s", self.name, motor.SlaveID, e)
        for motor in self.motors:
            try:
                mode = Control_Type.Torque_Pos if motor is self.motors[6] else Control_Type.POS_VEL
                self.motor_control.switchControlMode(motor, mode)
                self.motor_control.enable(motor)
                time.sleep(0.005)
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] re-enable id=%d failed: %s", self.name, motor.SlaveID, e)
        for motor in self.motors:
            try:
                self.motor_control.refresh_motor_status(motor)
                time.sleep(0.002)
            except Exception as e:  # noqa: BLE001
                log.debug("[%s] refresh id=%d failed: %s", self.name, motor.SlaveID, e)
        log.info("[%s] recover done", self.name)

    def get_measured_joint_states(self) -> dict:
        """Return state_q for each motor (last cache, refreshed by recover())."""
        if not self.motors:
            return {}
        out: dict = {}
        for i in range(min(6, len(self.motors))):
            out[f"joint{i+1}"] = float(getattr(self.motors[i], "state_q", 0.0))
        if len(self.motors) > 6:
            out["gripper"] = float(getattr(self.motors[6], "state_q", 0.0))
        return out

    def safe_shutdown(self, duration: float = 2.0, steps: int = 20) -> None:
        if not self.motor_control or not self.motors:
            return
        try:
            log.info("[%s] safe shutdown: slow zero → disable", self.name)
            current = []
            for motor in self.motors:
                pos = 0.0
                try:
                    if hasattr(motor, "state") and hasattr(motor.state, "pos"):
                        pos = float(motor.state.pos)
                    elif hasattr(motor, "pos"):
                        pos = float(motor.pos)
                except Exception:  # noqa: BLE001
                    pos = 0.0
                current.append(pos)

            target = [0.0] * len(self.motors)
            dt = duration / steps if steps > 0 else 0.02

            for step in range(1, steps + 1):
                a = step / steps
                a = a * a * (3 - 2 * a)
                for i in range(6):
                    pos = current[i] + a * (target[i] - current[i])
                    self.motor_control.control_Pos_Vel(self.motors[i], pos, 0.8)
                    time.sleep(0.002)
                grip = current[6] + a * (target[6] - current[6])
                self.motor_control.control_pos_force(self.motors[6], grip, 1000, 200)
                time.sleep(dt)

            for motor in self.motors:
                try:
                    self.motor_control.disable(motor)
                    time.sleep(0.002)
                except Exception as e:  # noqa: BLE001
                    log.warning("[%s] disable failed: %s", self.name, e)
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] safe_shutdown error: %s", self.name, e)

    def close(self) -> None:
        try:
            if self.serial_device is not None and self.serial_device.is_open:
                self.serial_device.close()
                log.info("[%s] serial closed", self.name)
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] close failed: %s", self.name, e)


# ---------------------------------------------------------------------------
# Mock master / slave — for laptop testing without hardware
# ---------------------------------------------------------------------------

# Per-joint sinusoid (amp_rad, period_s, phase_offset). Different periods so
# the joint bars look organic, not synchronized.
_MOCK_JOINT_WAVES = {
    "joint1": (0.9, 8.0, 0.0),
    "joint2": (0.6, 6.5, 1.0),
    "joint3": (0.7, 5.5, 2.0),
    "joint4": (0.8, 7.0, 0.5),
    "joint5": (0.5, 4.5, 1.5),
    "joint6": (0.6, 5.0, 2.5),
}


class MockMaster:
    """Stand-in for PiPER_MateAgilex. Returns a deterministic, slowly-moving pose."""

    def __init__(self, gripper_exist: bool = True):
        self.gripper_exist = gripper_exist
        self._t0 = time.monotonic()

    def get_fashionstar_joint_states(self) -> dict:
        t = time.monotonic() - self._t0
        js: dict = {}
        for k, (amp, period, phase) in _MOCK_JOINT_WAVES.items():
            js[k] = amp * math.sin(2 * math.pi * t / period + phase)
        # Gripper: smooth 0..1 wave so the bar visibly moves.
        js["gripper"] = 0.5 + 0.5 * math.sin(2 * math.pi * t / 9.0)
        return js

    def close(self) -> None:
        pass


class MockSlave:
    """Stand-in for SlaveArm. Accepts joint targets but does nothing."""

    def __init__(self, name: str = "mock_slave"):
        self.name = name
        self.port = "<mock>"

    def setup(self) -> None:
        log.info("[%s] mock slave initialized (no serial I/O)", self.name)

    def send_joint_states(self, js: dict) -> None:
        # No-op. The Controller still records last_output_joint_states from
        # this call's argument, which is what the WS snapshot exposes.
        return

    def recover(self) -> None:
        return

    def get_measured_joint_states(self) -> dict:
        return {}

    def safe_shutdown(self, duration: float = 2.0, steps: int = 20) -> None:
        return

    def close(self) -> None:
        return


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ControllerError(Exception):
    """Raised when a command is invalid in the current mode."""


class Controller:
    def __init__(self, cfg: Config, library: ActionLibrary):
        self.cfg = cfg
        self.library = library

        # ---- runtime state (all guarded by self.lock) ----
        self.lock = threading.RLock()
        self.running = True
        self.mode: ControllerMode = "follow"
        self.safety_enabled: bool = cfg.safety_default_enabled
        self._recovering: bool = False

        # Recording
        self.record_buffer: list[dict] = []
        self.record_action_name: Optional[str] = None
        self.record_start_time: Optional[float] = None
        self.last_recorded_time: Optional[float] = None
        self.last_recorded_joint_states: Optional[dict] = None

        # Playback
        self.current_action: Optional[Action] = None     # Action being played
        self.current_play_mode: Optional[PlayMode] = None
        self.play_start_time: Optional[float] = None
        self.play_index: int = 0

        # Transition (current_output → action[0])
        self.transition_start_time: Optional[float] = None
        self.transition_from_js: Optional[dict] = None
        self.transition_to_js: Optional[dict] = None
        self.transition_target_action: Optional[Action] = None
        self.transition_target_mode: Optional[PlayMode] = None

        # Return-to-follow (current_output → live master) — used after "once" playback
        self.return_start_time: Optional[float] = None
        self.return_from_js: Optional[dict] = None

        # Master/slave shared state
        self.last_joint_states: Optional[dict] = None        # last master read
        self.last_output_joint_states: Optional[dict] = None # last slave write
        self.frame_count: int = 0
        self.last_error: Optional[str] = None

        # Hardware (set in setup_hardware)
        self.master: Optional[PiPER_MateAgilex] = None
        self.slaves: list[SlaveArm] = []

        # Snapshot listeners (e.g., WS broadcaster)
        self._listeners: list = []

    # ------------------------------------------------------------------
    # Hardware setup / teardown
    # ------------------------------------------------------------------
    def setup_hardware(self) -> None:
        if self.cfg.mock:
            log.warning(
                "REBOT_MOCK=1: synthesizing joint data, no serial I/O. "
                "Use this for UI testing only."
            )
            self.master = MockMaster(gripper_exist=self.cfg.gripper_exist)
            mock_slave = MockSlave("mock_slave_1")
            mock_slave.setup()
            self.slaves = [mock_slave]
            return

        master_port = self.cfg.master_port
        slave_port = self.cfg.slave_port
        if not master_port or not slave_port:
            detected_master, detected_slave = detect_ports(master_port, slave_port)
            master_port = master_port or detected_master
            slave_port = slave_port or detected_slave
        if not master_port:
            raise RuntimeError("Master arm port not found; set MASTER_PORT or check USB")
        if not slave_port:
            raise RuntimeError("Slave arm port not found; set SLAVE_PORT or check USB")

        slave = SlaveArm(slave_port, self.cfg.baudrate, "slave_1")
        slave.setup()
        self.slaves = [slave]

        self.master = PiPER_MateAgilex(
            fashionstar_port=master_port,
            gripper_exist=self.cfg.gripper_exist,
        )
        log.info("Master arm initialized on %s", master_port)

    def cleanup(self) -> None:
        log.info("Cleaning up hardware...")
        self.running = False
        try:
            if self.master is not None:
                self.master.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Master close failed: %s", e)
        for s in self.slaves:
            try:
                s.safe_shutdown()
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] safe_shutdown failed: %s", s.name, e)
            try:
                s.close()
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] close failed: %s", s.name, e)
        log.info("Cleanup complete.")

    def request_shutdown(self) -> None:
        log.info("Shutdown requested")
        self.running = False

    def add_listener(self, fn) -> None:
        """Register fn(snapshot_dict). Called from the control thread."""
        self._listeners.append(fn)

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _filter(new_js: dict, last: Optional[dict], alpha: float) -> dict:
        if last is None:
            return deepcopy(new_js)
        return {k: last[k] + alpha * (new_js[k] - last[k]) for k in new_js}

    @staticmethod
    def _changed_enough(a: Optional[dict], b: Optional[dict], threshold: float) -> bool:
        if a is None or b is None:
            return True
        return any(abs(a[k] - b[k]) > threshold for k in a)

    @staticmethod
    def _interpolate(frame_a: dict, frame_b: dict, t_now: float) -> dict:
        t0, t1 = frame_a["t"], frame_b["t"]
        js0, js1 = frame_a["joint_states"], frame_b["joint_states"]
        if abs(t1 - t0) < 1e-9:
            return deepcopy(js0)
        a = max(0.0, min(1.0, (t_now - t0) / (t1 - t0)))
        a = a * a * (3 - 2 * a)
        return {k: js0[k] + a * (js1[k] - js0[k]) for k in js0}

    @staticmethod
    def _blend(js_from: dict, js_to: dict, alpha: float) -> dict:
        a = max(0.0, min(1.0, alpha))
        a = a * a * (3 - 2 * a)
        return {k: js_from[k] + a * (js_to[k] - js_from[k]) for k in js_from}

    def _current_output_js(self) -> Optional[dict]:
        if self.last_output_joint_states is not None:
            return deepcopy(self.last_output_joint_states)
        if self.last_joint_states is not None:
            return deepcopy(self.last_joint_states)
        return None

    def _broadcast_to_slaves(self, js: dict) -> None:
        for slave in self.slaves:
            slave.send_joint_states(js)
        self.last_output_joint_states = deepcopy(js)

    def _apply_safety(self, js: dict, dt: float) -> Optional[dict]:
        """Filter master input before sending to slave.

        Returns the slew-limited joint dict, or None if a spike was detected
        (caller should pause). Gripper is passed through untouched.
        Operates against last_output_joint_states; first-tick has no baseline
        so we let the raw frame through.
        """
        last = self.last_output_joint_states
        if last is None:
            return js
        spike = self.cfg.spike_threshold_rad
        for k, v in js.items():
            if k == "gripper" or k not in last:
                continue
            if abs(v - last[k]) > spike:
                log.warning("Safety: spike on %s (Δ=%.3f rad), pausing", k, v - last[k])
                return None
        max_step = self.cfg.max_joint_vel_rad_s * dt
        out = {}
        for k, v in js.items():
            if k == "gripper" or k not in last:
                out[k] = v
                continue
            delta = v - last[k]
            if delta > max_step:
                out[k] = last[k] + max_step
            elif delta < -max_step:
                out[k] = last[k] - max_step
            else:
                out[k] = v
        return out

    # ------------------------------------------------------------------
    # Public commands (called by REST handlers)
    # ------------------------------------------------------------------
    def start_record(self, name: Optional[str] = None) -> None:
        with self.lock:
            if self.mode == "record":
                raise ControllerError("Already recording")
            self._stop_active_locked()
            self.record_buffer = []
            self.record_action_name = name
            self.record_start_time = time.monotonic()
            self.last_recorded_time = 0.0
            self.last_recorded_joint_states = None
            self.mode = "record"
            if self.last_joint_states is not None:
                init = deepcopy(self.last_joint_states)
                self.record_buffer.append({"t": 0.0, "joint_states": init})
                self.last_recorded_joint_states = deepcopy(init)
            log.info("Recording started (name=%s)", name)

    def stop_record(self) -> Action:
        with self.lock:
            if self.mode != "record":
                raise ControllerError("Not currently recording")
            frames = self.record_buffer
            # Append end-hold frame so the arm settles. Loop blend is now
            # synthesized at playback time, so don't bake the loop-back frame in.
            if frames:
                last = deepcopy(frames[-1])
                frames.append({
                    "t": last["t"] + self.cfg.end_hold_time_s,
                    "joint_states": deepcopy(last["joint_states"]),
                })
            name = self.record_action_name
            self.record_buffer = []
            self.record_action_name = None
            self.record_start_time = None
            self.last_recorded_time = None
            self.last_recorded_joint_states = None
            self.mode = "follow"
            if not frames:
                log.warning("Recording stopped with no frames; nothing saved")
                raise ControllerError("Recording produced no frames")
            action = self.library.create(frames=frames, name=name)
            log.info("Recording saved as action %s (%s)", action.id, action.name)
            return action

    def start_playback(self, action_id: str, mode: PlayMode) -> Action:
        action = self.library.get(action_id)
        if not action.frames:
            raise ControllerError(f"Action {action_id} has no frames")
        with self.lock:
            self._stop_active_locked()
            from_js = self._current_output_js()
            to_js = deepcopy(action.frames[0]["joint_states"])
            if from_js is None:
                # No reference pose yet — start playback immediately.
                self._begin_playback_locked(action, mode)
                return action
            self.transition_start_time = time.monotonic()
            self.transition_from_js = from_js
            self.transition_to_js = to_js
            self.transition_target_action = action
            self.transition_target_mode = mode
            self.mode = "transition"
            log.info("Transition → action %s (mode=%s)", action.id, mode)
            return action

    def stop_playback(self) -> None:
        with self.lock:
            if self.mode in ("playback", "transition", "return_to_follow"):
                self._stop_active_locked()
                self.mode = "follow"

    def force_follow(self) -> None:
        with self.lock:
            self._stop_active_locked()
            self.mode = "follow"
            log.info("Forced follow mode")

    def pause(self) -> None:
        """Emergency stop: stop sending commands to the slave so it holds at
        the last commanded pose. Master is still polled so we can resume into
        the operator's current pose, but its motion is not broadcast.
        Discards any in-progress record/playback.
        """
        with self.lock:
            if self.mode == "paused":
                return
            self._stop_active_locked()
            self.mode = "paused"
            log.warning("Paused (slave holding at last pose)")

    def resume(self) -> None:
        """Leave paused mode by slow-blending the slave from its held pose to
        the live master pose, then dropping to follow.
        """
        with self.lock:
            if self.mode != "paused":
                return
            self._begin_return_to_follow_locked()
            log.info("Resumed (return_to_follow blending to master)")

    def set_safety(self, enabled: bool) -> None:
        with self.lock:
            self.safety_enabled = bool(enabled)
            log.warning("Safety mode %s", "ENABLED" if enabled else "DISABLED")
            if not enabled:
                self.last_error = None  # clear stale spike warning

    def recover(self) -> dict:
        """Two-phase recovery from a single DM motor's CAN/power line being
        unplugged and re-plugged. Designed to be safe against accidental presses:

        Phase 1 — slow-blend slave to home pose (all 6 arm joints = 0, gripper held).
                  If it was a false alarm, this is the entire visible effect: the
                  arm just goes to zero pose. The operator can press 解除锁定
                  during the blend to abort and skip Phase 2.
        Phase 2 — disable → switchControlMode → enable → refresh_motor_status
                  per motor, then rebase last_output_joint_states to measured.
        End state — controller stays paused. Operator presses 解除锁定 to
                    slow-blend back to live master via return_to_follow.

        NOTE: DM 4310/4340 single-turn encoders lose their zero on power loss.
        If the unplugged motor was without power, its post-recovery angle will
        be offset from the original frame by an unknown amount. Software cannot
        fix this — burn the zero pose to flash (``save_pos_zero``) once for a
        permanent fix, or accept the operational offset.
        """
        with self.lock:
            if self._recovering:
                log.info("Recover already in progress")
                return self.snapshot()
            self._recovering = True
            self._stop_active_locked()
            self.mode = "paused"
            self.last_error = None
            from_js = deepcopy(self.last_output_joint_states or self.last_joint_states or {})
        log.warning("Recover requested")

        try:
            # ---- Phase 1: slow-blend to home pose ----
            aborted = False
            if from_js:
                home_js = {k: 0.0 for k in from_js}
                if "gripper" in from_js:
                    home_js["gripper"] = from_js["gripper"]   # don't slam the gripper
                log.warning("Recover Phase 1: blend → home over %.1fs",
                            self.cfg.recover_blend_time_s)
                aborted = not self._blend_slave_during_recover(from_js, home_js)
                if aborted:
                    log.warning("Recover aborted during blend — skipping handshake")

            # ---- Phase 2: re-handshake (skip if aborted) ----
            if not aborted:
                log.warning("Recover Phase 2: re-handshaking slave motors")
                errors: list[str] = []
                for slave in self.slaves:
                    try:
                        slave.recover()
                    except Exception as e:  # noqa: BLE001
                        log.exception("[%s] recover failed", slave.name)
                        errors.append(f"{slave.name}: {e}")

                # ---- Phase 3: rebase software pose to measured ----
                measured: dict = {}
                for slave in self.slaves:
                    try:
                        m = slave.get_measured_joint_states() if hasattr(slave, "get_measured_joint_states") else {}
                        if m:
                            measured = m
                            break
                    except Exception as e:  # noqa: BLE001
                        log.warning("get_measured failed: %s", e)

                with self.lock:
                    base = dict(self.last_output_joint_states or self.last_joint_states or {})
                    for k, v in measured.items():
                        if k != "gripper":
                            base[k] = v
                    if base:
                        self.last_output_joint_states = base
                        log.info("Recover: rebased last_output to measured pose")
                    if errors:
                        self.last_error = "recover: " + "; ".join(errors)
        finally:
            with self.lock:
                self._recovering = False
        return self.snapshot()

    def _blend_slave_during_recover(self, from_js: dict, to_js: dict) -> bool:
        """Slow-blend slave from from_js → to_js, bypassing the control thread.

        Caller must have set mode=paused and self._recovering=True. The control
        thread won't write to the slave while paused, so this is the only writer.
        Returns True if blend completed, False if user aborted (resume pressed,
        which flipped mode to return_to_follow).
        """
        duration = self.cfg.recover_blend_time_s
        if duration <= 0 or not self.slaves:
            return True
        steps = max(1, int(duration * self.cfg.update_rate_hz))
        dt = duration / steps
        for step in range(1, steps + 1):
            with self.lock:
                if self.mode != "paused":
                    return False    # user aborted
            a = step / steps
            a = a * a * (3 - 2 * a)
            js = {k: from_js[k] + a * (to_js[k] - from_js[k]) for k in from_js}
            for slave in self.slaves:
                try:
                    slave.send_joint_states(js)
                except Exception as e:  # noqa: BLE001
                    log.warning("[%s] recover blend send failed: %s", slave.name, e)
            with self.lock:
                self.last_output_joint_states = deepcopy(js)
            time.sleep(dt)
        return True

    # ------------------------------------------------------------------
    # Internal mode transitions
    # ------------------------------------------------------------------
    def _stop_active_locked(self) -> None:
        """Drop any active record/playback/transition/return_to_follow state.
        Caller must hold self.lock and is responsible for setting the new mode.
        """
        if self.mode == "record":
            # Discard the in-progress recording; do not save a partial.
            self.record_buffer = []
            self.record_action_name = None
            self.record_start_time = None
            self.last_recorded_time = None
            self.last_recorded_joint_states = None
        self.current_action = None
        self.current_play_mode = None
        self.play_start_time = None
        self.play_index = 0
        self.transition_start_time = None
        self.transition_from_js = None
        self.transition_to_js = None
        self.transition_target_action = None
        self.transition_target_mode = None
        self.return_start_time = None
        self.return_from_js = None

    def _begin_playback_locked(self, action: Action, mode: PlayMode) -> None:
        self.current_action = action
        self.current_play_mode = mode
        self.play_start_time = time.monotonic()
        self.play_index = 0
        self.mode = "playback"
        log.info("Playback start: %s (%s, %.2fs, %s)",
                 action.id, action.name, action.duration_s, mode)

    def _begin_return_to_follow_locked(self) -> None:
        self.return_start_time = time.monotonic()
        self.return_from_js = self._current_output_js() or {}
        self.current_action = None
        self.current_play_mode = None
        self.play_start_time = None
        self.play_index = 0
        self.mode = "return_to_follow"
        log.info("Return-to-follow start (%.2fs)", self.cfg.return_time_s)

    # ------------------------------------------------------------------
    # Per-tick updates
    # ------------------------------------------------------------------
    def _update_recording(self, js: dict) -> None:
        with self.lock:
            if self.mode != "record" or self.record_start_time is None:
                return
            t_rel = time.monotonic() - self.record_start_time
            if (self.last_recorded_time is not None
                    and (t_rel - self.last_recorded_time) < self.cfg.min_record_interval_s):
                return
            filtered = self._filter(js, self.last_recorded_joint_states,
                                    alpha=self.cfg.record_filter_alpha)
            if not self._changed_enough(filtered, self.last_recorded_joint_states,
                                        threshold=self.cfg.min_joint_change_rad):
                return
            self.record_buffer.append({"t": t_rel, "joint_states": deepcopy(filtered)})
            self.last_recorded_joint_states = deepcopy(filtered)
            self.last_recorded_time = t_rel

    def _update_transition(self) -> Optional[dict]:
        with self.lock:
            if self.mode != "transition":
                return None
            if self.transition_from_js is None or self.transition_to_js is None:
                self._stop_active_locked()
                self.mode = "follow"
                return None
            elapsed = time.monotonic() - self.transition_start_time
            T = self.cfg.transition_time_s
            alpha = elapsed / T if T > 1e-9 else 1.0
            if alpha >= 1.0:
                action = self.transition_target_action
                mode = self.transition_target_mode or "loop"
                self.transition_start_time = None
                self.transition_from_js = None
                self.transition_to_js = None
                self.transition_target_action = None
                self.transition_target_mode = None
                if action is not None:
                    self._begin_playback_locked(action, mode)
                else:
                    self.mode = "follow"
                return None
            return self._blend(self.transition_from_js, self.transition_to_js, alpha)

    def _update_playback(self) -> Optional[dict]:
        with self.lock:
            if self.mode != "playback" or self.current_action is None:
                return None
            seq = self.current_action.frames
            if not seq:
                self._stop_active_locked()
                self.mode = "follow"
                return None
            if len(seq) == 1:
                return deepcopy(seq[0]["joint_states"])

            elapsed = time.monotonic() - self.play_start_time
            total = seq[-1]["t"]
            if total <= 1e-9:
                return deepcopy(seq[-1]["joint_states"])

            # End of sequence reached
            if elapsed > total:
                if self.current_play_mode == "loop":
                    blend_t = self.cfg.loop_blend_time_s
                    over = elapsed - total
                    if over < blend_t and blend_t > 1e-9:
                        # Smooth blend from last → first to hide the wrap discontinuity.
                        return self._blend(
                            seq[-1]["joint_states"],
                            seq[0]["joint_states"],
                            over / blend_t,
                        )
                    # Reset playback head past the blend window.
                    self.play_start_time = time.monotonic() - (over - blend_t)
                    self.play_index = 0
                    elapsed = over - blend_t
                else:  # "once"
                    self._begin_return_to_follow_locked()
                    return self.return_from_js or None

            # Advance index
            while (self.play_index < len(seq) - 1
                   and seq[self.play_index + 1]["t"] < elapsed):
                self.play_index += 1
            while self.play_index > 0 and seq[self.play_index]["t"] > elapsed:
                self.play_index -= 1

            i = self.play_index
            if i >= len(seq) - 1:
                return deepcopy(seq[-1]["joint_states"])
            return self._interpolate(seq[i], seq[i + 1], elapsed)

    def _update_return_to_follow(self) -> Optional[dict]:
        """Slow blend from playback-end pose → live master pose, then resume follow.

        Re-samples master each tick (option (b)): if the operator is moving the
        master during the return window, the slave tracks toward wherever the
        master currently is. Master read failure raises and is fatal.
        """
        if self.mode != "return_to_follow":
            return None
        # NB: read master OUTSIDE the lock (serial I/O can be slow), then update state.
        master_js = self.master.get_fashionstar_joint_states() if self.master else None
        with self.lock:
            if self.mode != "return_to_follow" or self.return_start_time is None:
                return None
            elapsed = time.monotonic() - self.return_start_time
            T = self.cfg.return_time_s
            alpha = min(1.0, elapsed / T) if T > 1e-9 else 1.0
            smooth = alpha * alpha * (3 - 2 * alpha)
            if not master_js:
                return deepcopy(self.last_output_joint_states or {})
            self.last_joint_states = deepcopy(master_js)
            if alpha >= 1.0:
                self._stop_active_locked()
                self.mode = "follow"
                return master_js
            return self._blend(self.return_from_js or master_js, master_js, smooth)

    # ------------------------------------------------------------------
    # State snapshot (for /api/state and WS broadcast)
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            recording_frames = (
                len(self.record_buffer) if self.mode == "record" else None
            )
            return {
                "ts": time.time(),
                "mode": self.mode,
                "safety_enabled": self.safety_enabled,
                "recovering": self._recovering,
                "active_action_id": (
                    self.current_action.id if self.current_action
                    else (self.transition_target_action.id if self.transition_target_action else None)
                ),
                "active_play_mode": (
                    self.current_play_mode
                    or self.transition_target_mode
                ),
                "frame_count": self.frame_count,
                "recording_frames": recording_frames,
                "joint_states": (
                    dict(self.last_output_joint_states) if self.last_output_joint_states
                    else (dict(self.last_joint_states) if self.last_joint_states else {})
                ),
                "last_error": self.last_error,
            }

    # ------------------------------------------------------------------
    # Main control loop (run in dedicated thread)
    # ------------------------------------------------------------------
    def run(self) -> None:
        update_interval = 1.0 / self.cfg.update_rate_hz
        push_interval = 1.0 / max(1, self.cfg.ws_push_hz)
        last_push = 0.0

        log.info("Control loop @ %dHz starting", self.cfg.update_rate_hz)
        try:
            while self.running:
                loop_start = time.monotonic()
                try:
                    with self.lock:
                        mode = self.mode

                    out_js: Optional[dict] = None

                    if mode in ("follow", "record"):
                        js = self.master.get_fashionstar_joint_states() if self.master else None
                        if js:
                            self.last_joint_states = deepcopy(js)
                            send_js = (
                                self._apply_safety(js, update_interval)
                                if self.safety_enabled else js
                            )
                            if send_js is None:
                                # Spike detected: hold slave, surface to UI.
                                self.last_error = "safety: spike on master input"
                                self.pause()
                            else:
                                self._broadcast_to_slaves(send_js)
                                out_js = send_js
                                if mode == "record":
                                    self._update_recording(send_js)
                                self.frame_count += 1
                    elif mode == "transition":
                        js = self._update_transition()
                        if js:
                            self._broadcast_to_slaves(js)
                            out_js = js
                            self.frame_count += 1
                    elif mode == "playback":
                        js = self._update_playback()
                        if js:
                            self._broadcast_to_slaves(js)
                            out_js = js
                            self.frame_count += 1
                    elif mode == "return_to_follow":
                        js = self._update_return_to_follow()
                        if js:
                            self._broadcast_to_slaves(js)
                            out_js = js
                            self.frame_count += 1
                    elif mode == "paused":
                        # Safety lockout: do not write to slave. Slave's PID
                        # holds the last commanded pose. Master is intentionally
                        # NOT polled so a child playing with it has zero effect
                        # on slave hardware.
                        pass

                    # Push snapshot to listeners at ws_push_hz (not every tick).
                    now = time.monotonic()
                    if now - last_push >= push_interval:
                        last_push = now
                        snap = self.snapshot()
                        for fn in self._listeners:
                            try:
                                fn(snap)
                            except Exception as e:  # noqa: BLE001
                                log.debug("listener error: %s", e)

                    sleep_time = max(0.0, update_interval - (time.monotonic() - loop_start))
                    time.sleep(sleep_time)

                except KeyboardInterrupt:
                    log.info("Control loop interrupted")
                    break
                except serial.SerialException as e:
                    log.error("Serial connection lost: %s", e)
                    self.last_error = f"serial: {e}"
                    break
                except OSError as e:
                    log.error("OS error: %s", e)
                    self.last_error = f"os: {e}"
                    break
                except Exception as e:  # noqa: BLE001
                    log.exception("Unexpected error in control loop")
                    self.last_error = str(e)
                    time.sleep(0.5)
        finally:
            self.cleanup()
