from pipermate_sdk import PiPER_MateAgilex
import time
import serial
import threading
from copy import deepcopy
from pynput import keyboard
from u2can.DM_CAN import *

from fashionstar_uart_sdk.uart_pocket_handler import (
    PortHandler as starai_PortHandler,
    SyncPositionControlOptions,
)


class SlaveArm:
    """
    单个从臂封装
    """
    def __init__(self, port, baudrate=921600, name="slave"):
        self.port = port
        self.baudrate = baudrate
        self.name = name

        self.serial_device = None
        self.motor_control = None
        self.motors = []

    def setup(self):
        self.serial_device = serial.Serial(
            self.port,
            self.baudrate,
            timeout=0.5
        )

        Motor1 = Motor(DM_Motor_Type.DM4340, 0x01, 0x11)
        Motor2 = Motor(DM_Motor_Type.DM4340, 0x02, 0x12)
        Motor3 = Motor(DM_Motor_Type.DM4340, 0x03, 0x13)
        Motor4 = Motor(DM_Motor_Type.DM4310, 0x04, 0x14)
        Motor5 = Motor(DM_Motor_Type.DM4310, 0x05, 0x15)
        Motor6 = Motor(DM_Motor_Type.DM4310, 0x06, 0x16)
        Motor7 = Motor(DM_Motor_Type.DM4310, 0x07, 0x17)

        self.motor_control = MotorControl(self.serial_device)
        self.motor_control.addMotor(Motor1)
        self.motor_control.addMotor(Motor2)
        self.motor_control.addMotor(Motor3)
        self.motor_control.addMotor(Motor4)
        self.motor_control.addMotor(Motor5)
        self.motor_control.addMotor(Motor6)
        self.motor_control.addMotor(Motor7)

        self.motors = [Motor1, Motor2, Motor3, Motor4, Motor5, Motor6, Motor7]

        for motor in self.motors:
            self.motor_control.enable(motor)
            time.sleep(0.05)

        print(f"[系统] {self.name} 初始化完成: {self.port}")

    def send_joint_states(self, joint_states):
        self.motor_control.control_Pos_Vel(self.motors[0], joint_states["joint1"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[1], joint_states["joint2"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[2], joint_states["joint3"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[3], joint_states["joint4"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[4], joint_states["joint5"], 15)
        time.sleep(0.0005)
        self.motor_control.control_Pos_Vel(self.motors[5], joint_states["joint6"], 15)
        time.sleep(0.0005)

        self.motor_control.control_pos_force(
            self.motors[6],
            joint_states["gripper"],
            2000,
            350
        )

    def safe_shutdown(self, duration=2.0, steps=20):
        """
        缓慢回零，然后依次失能
        """
        if not self.motor_control or not self.motors:
            return

        try:
            print(f"[系统] {self.name} 开始安全下电：缓慢回零 -> 失能")

            current_positions = []
            for motor in self.motors:
                pos = 0.0
                try:
                    if hasattr(motor, "state") and hasattr(motor.state, "pos"):
                        pos = float(motor.state.pos)
                    elif hasattr(motor, "pos"):
                        pos = float(motor.pos)
                except Exception:
                    pos = 0.0
                current_positions.append(pos)

            target_positions = [0.0] * len(self.motors)
            dt = duration / steps if steps > 0 else 0.02

            for step in range(1, steps + 1):
                alpha = step / steps
                alpha = alpha * alpha * (3 - 2 * alpha)

                for i in range(6):
                    pos = current_positions[i] + alpha * (target_positions[i] - current_positions[i])
                    self.motor_control.control_Pos_Vel(self.motors[i], pos, 0.8)
                    time.sleep(0.002)

                grip_pos = current_positions[6] + alpha * (target_positions[6] - current_positions[6])
                self.motor_control.control_pos_force(self.motors[6], grip_pos, 1000, 200)
                time.sleep(dt)

            print(f"[系统] {self.name} 回零完成，开始失能")

            for motor in self.motors:
                try:
                    self.motor_control.disable(motor)
                    time.sleep(0.002)
                except Exception as e:
                    print(f"[清理] {self.name} 某电机失能失败: {e}")

            print(f"[系统] {self.name} 已完成失能")

        except Exception as e:
            print(f"[清理] {self.name} 安全下电失败: {e}")

    def close(self):
        try:
            if self.serial_device is not None and self.serial_device.is_open:
                self.serial_device.close()
                print(f"[系统] {self.name} 串口已关闭: {self.port}")
        except Exception as e:
            print(f"[清理] {self.name} 关闭失败: {e}")


class TeleopLooper:
    def __init__(self):
        # =========================
        # 预设参数
        # =========================
        self.PIPERMATE_PORT = "COM12"
        self.SLAVE_PORTS = [
            "COM3",
            #"/dev/ttyACM1",
        ]
        self.BAUDRATE = 921600
        self.GRIPPER_EXIST = True
        self.UPDATE_RATE = 30

        self.PLAY_LOOP = True
        self.NUM_SLOTS = 5

        # 轨迹优化参数
        self.END_HOLD_TIME = 0.15
        self.LOOP_BLEND_TIME = 0.30
        self.RECORD_FILTER_ALPHA = 0.35
        self.MIN_RECORD_INTERVAL = 0.01
        self.MIN_JOINT_CHANGE = 0.003

        # 槽位切换滤波参数（1~5 动作之间的平滑过渡）
        self.TRANSITION_TIME = 0.6

        self.record_keys = {
            "q": 0,
            "w": 1,
            "e": 2,
            "r": 3,
            "t": 4,
        }
        self.play_keys = {
            "1": 0,
            "2": 1,
            "3": 2,
            "4": 3,
            "5": 4,
        }

        # =========================
        # 运行状态
        # =========================
        self.running = True
        self.lock = threading.RLock()
        self.mode = "follow"   # follow / record / transition / playback

        self.motion_slots = [[] for _ in range(self.NUM_SLOTS)]

        self.current_record_slot = None
        self.current_play_slot = None
        self.last_operated_slot = None

        self.record_start_time = None
        self.play_start_time = None
        self.play_index = 0

        # 录制辅助
        self.last_joint_states = None
        self.last_recorded_joint_states = None
        self.last_recorded_time = None

        # 槽位切换过渡状态
        self.transition_start_time = None
        self.transition_from_js = None
        self.transition_to_js = None
        self.transition_target_slot = None

        # 当前输出给从臂的姿态缓存
        self.last_output_joint_states = None

        # 设备对象
        self.robot_controller = None
        self.slaves = []

    # =========================================================
    # 设备初始化
    # =========================================================
    def setup_slaves(self):
        self.slaves = []

        for idx, port in enumerate(self.SLAVE_PORTS):
            slave = SlaveArm(
                port=port,
                baudrate=self.BAUDRATE,
                name=f"slave_{idx+1}"
            )
            slave.setup()
            self.slaves.append(slave)

    def setup_master_arm(self):
        self.robot_controller = PiPER_MateAgilex(
            fashionstar_port=self.PIPERMATE_PORT,
            gripper_exist=self.GRIPPER_EXIST
        )
        print(f"[系统] 主臂初始化完成: {self.PIPERMATE_PORT}")

    # =========================================================
    # 广播到所有从臂
    # =========================================================
    def send_joint_states_to_all_slaves(self, joint_states):
        for slave in self.slaves:
            try:
                slave.send_joint_states(joint_states)
            except Exception as e:
                print(f"\n发送到 {slave.name} 失败: {e}")
                raise

        self.last_output_joint_states = deepcopy(joint_states)

    # =========================================================
    # 工具函数
    # =========================================================
    def filter_joint_states(self, new_js, last_js, alpha=0.35):
        if last_js is None:
            return deepcopy(new_js)

        filtered = {}
        for k in new_js.keys():
            filtered[k] = last_js[k] + alpha * (new_js[k] - last_js[k])
        return filtered

    def joint_states_changed_enough(self, js1, js2, threshold=0.003):
        if js1 is None or js2 is None:
            return True

        for k in js1.keys():
            if abs(js1[k] - js2[k]) > threshold:
                return True
        return False

    def interpolate_joint_states(self, frame_a, frame_b, t_now):
        t0 = frame_a["t"]
        t1 = frame_b["t"]
        js0 = frame_a["joint_states"]
        js1 = frame_b["joint_states"]

        if abs(t1 - t0) < 1e-9:
            return deepcopy(js0)

        alpha = (t_now - t0) / (t1 - t0)
        alpha = max(0.0, min(1.0, alpha))
        alpha = alpha * alpha * (3 - 2 * alpha)

        interpolated = {}
        for joint in js0.keys():
            interpolated[joint] = js0[joint] + alpha * (js1[joint] - js0[joint])

        return interpolated

    def blend_joint_states(self, js_from, js_to, alpha):
        alpha = max(0.0, min(1.0, alpha))
        alpha = alpha * alpha * (3 - 2 * alpha)

        blended = {}
        for joint in js_from.keys():
            blended[joint] = js_from[joint] + alpha * (js_to[joint] - js_from[joint])
        return blended

    def get_current_output_joint_states(self):
        """
        获取当前实际输出给从臂的姿态，优先使用 last_output_joint_states
        """
        if self.last_output_joint_states is not None:
            return deepcopy(self.last_output_joint_states)

        if self.last_joint_states is not None:
            return deepcopy(self.last_joint_states)

        return None

    def clear_transition_state(self):
        self.transition_start_time = None
        self.transition_from_js = None
        self.transition_to_js = None
        self.transition_target_slot = None

    # =========================================================
    # 录制 / 播放 控制
    # =========================================================
    def start_record(self, slot_idx):
        with self.lock:
            if self.mode == "playback":
                self.stop_playback_locked()
            elif self.mode == "transition":
                self.stop_transition_locked()

            self.motion_slots[slot_idx] = []
            self.current_record_slot = slot_idx
            self.last_operated_slot = slot_idx
            self.record_start_time = time.monotonic()
            self.last_recorded_time = 0.0
            self.mode = "record"
            self.last_recorded_joint_states = None

            if self.last_joint_states is not None:
                init_js = deepcopy(self.last_joint_states)
                self.motion_slots[slot_idx].append({
                    "t": 0.0,
                    "joint_states": init_js
                })
                self.last_recorded_joint_states = deepcopy(init_js)

            print(f"\n[录制] 开始录制槽位 {slot_idx + 1}")

    def stop_record(self):
        with self.lock:
            if self.mode != "record":
                return
            self.stop_record_locked()

    def stop_record_locked(self):
        slot_idx = self.current_record_slot

        if slot_idx is not None and len(self.motion_slots[slot_idx]) > 0:
            last_frame = deepcopy(self.motion_slots[slot_idx][-1])
            first_frame = deepcopy(self.motion_slots[slot_idx][0])

            hold_frame = {
                "t": last_frame["t"] + self.END_HOLD_TIME,
                "joint_states": deepcopy(last_frame["joint_states"])
            }
            self.motion_slots[slot_idx].append(hold_frame)

            if self.PLAY_LOOP:
                loop_back_frame = {
                    "t": hold_frame["t"] + self.LOOP_BLEND_TIME,
                    "joint_states": deepcopy(first_frame["joint_states"])
                }
                self.motion_slots[slot_idx].append(loop_back_frame)

        frame_num = len(self.motion_slots[slot_idx]) if slot_idx is not None else 0
        self.current_record_slot = None
        self.record_start_time = None
        self.last_recorded_time = None
        self.last_recorded_joint_states = None
        self.mode = "follow"

        print(f"\n[录制] 停止录制槽位 {slot_idx + 1 if slot_idx is not None else '?'}，共记录 {frame_num} 帧")

    def start_playback(self, slot_idx):
        with self.lock:
            if len(self.motion_slots[slot_idx]) == 0:
                print(f"\n[播放] 槽位 {slot_idx + 1} 没有录制内容")
                return

            if self.mode == "record":
                self.stop_record_locked()
            elif self.mode == "transition":
                self.stop_transition_locked()

            self.current_play_slot = slot_idx
            self.last_operated_slot = slot_idx
            self.play_start_time = time.monotonic()
            self.play_index = 0
            self.mode = "playback"

            total_time = self.motion_slots[slot_idx][-1]["t"] if self.motion_slots[slot_idx] else 0.0
            print(f"\n[播放] 开始播放槽位 {slot_idx + 1}，时长 {total_time:.3f}s，循环={'开' if self.PLAY_LOOP else '关'}")

    def start_transition_to_slot(self, slot_idx):
        with self.lock:
            if len(self.motion_slots[slot_idx]) == 0:
                print(f"\n[播放] 槽位 {slot_idx + 1} 没有录制内容")
                return

            if self.mode == "record":
                self.stop_record_locked()

            from_js = self.get_current_output_joint_states()
            to_js = deepcopy(self.motion_slots[slot_idx][0]["joint_states"])

            if from_js is None:
                self.start_playback(slot_idx)
                return

            self.transition_start_time = time.monotonic()
            self.transition_from_js = deepcopy(from_js)
            self.transition_to_js = deepcopy(to_js)
            self.transition_target_slot = slot_idx
            self.current_play_slot = None
            self.play_start_time = None
            self.play_index = 0
            self.last_operated_slot = slot_idx
            self.mode = "transition"

            print(f"\n[过渡] 动作切换到槽位 {slot_idx + 1}")

    def stop_playback(self):
        with self.lock:
            if self.mode != "playback":
                return
            self.stop_playback_locked()

    def stop_playback_locked(self):
        slot_idx = self.current_play_slot
        self.current_play_slot = None
        self.play_start_time = None
        self.play_index = 0
        self.mode = "follow"
        print(f"\n[播放] 停止播放槽位 {slot_idx + 1 if slot_idx is not None else '?'}")

    def stop_transition_locked(self):
        target_slot = self.transition_target_slot
        self.clear_transition_state()
        self.mode = "follow"
        print(f"\n[过渡] 停止动作切换 {target_slot + 1 if target_slot is not None else '?'}")

    def stop_all_actions(self):
        with self.lock:
            if self.mode == "record":
                self.stop_record_locked()
            elif self.mode == "playback":
                self.stop_playback_locked()
            elif self.mode == "transition":
                self.stop_transition_locked()
            else:
                print("\n[停止] 当前没有录制、播放或过渡任务")

    def clear_slot(self, slot_idx):
        with self.lock:
            if self.mode == "record" and self.current_record_slot == slot_idx:
                self.stop_record_locked()
            if self.mode == "playback" and self.current_play_slot == slot_idx:
                self.stop_playback_locked()
            if self.mode == "transition" and self.transition_target_slot == slot_idx:
                self.stop_transition_locked()

            self.motion_slots[slot_idx] = []
            print(f"\n[清空] 已清空槽位 {slot_idx + 1}")

    def clear_last_slot(self):
        with self.lock:
            if self.last_operated_slot is None:
                print("\n[清空] 当前没有最近操作的槽位")
                return
            slot_idx = self.last_operated_slot

        self.clear_slot(slot_idx)

    def clear_all_slots(self):
        with self.lock:
            if self.mode == "record":
                self.stop_record_locked()
            if self.mode == "playback":
                self.stop_playback_locked()
            if self.mode == "transition":
                self.stop_transition_locked()

            for i in range(self.NUM_SLOTS):
                self.motion_slots[i] = []

            print("\n[清空] 已清空所有动作槽位")

    # =========================================================
    # 录制 / 播放 / 过渡 更新
    # =========================================================
    def update_recording(self, joint_states):
        with self.lock:
            if self.mode != "record" or self.current_record_slot is None:
                return

            t_rel = time.monotonic() - self.record_start_time

            if self.last_recorded_time is not None:
                if (t_rel - self.last_recorded_time) < self.MIN_RECORD_INTERVAL:
                    return

            filtered_js = self.filter_joint_states(
                joint_states,
                self.last_recorded_joint_states,
                alpha=self.RECORD_FILTER_ALPHA
            )

            if not self.joint_states_changed_enough(
                filtered_js,
                self.last_recorded_joint_states,
                threshold=self.MIN_JOINT_CHANGE
            ):
                return

            self.motion_slots[self.current_record_slot].append({
                "t": t_rel,
                "joint_states": deepcopy(filtered_js)
            })

            self.last_recorded_joint_states = deepcopy(filtered_js)
            self.last_recorded_time = t_rel

    def update_transition(self):
        with self.lock:
            if self.mode != "transition":
                return None

            if self.transition_from_js is None or self.transition_to_js is None:
                self.clear_transition_state()
                self.mode = "follow"
                return None

            elapsed = time.monotonic() - self.transition_start_time
            alpha = elapsed / self.TRANSITION_TIME if self.TRANSITION_TIME > 1e-9 else 1.0

            if alpha >= 1.0:
                result_js = deepcopy(self.transition_to_js)
                target_slot = self.transition_target_slot

                self.clear_transition_state()

                self.current_play_slot = target_slot
                self.play_start_time = time.monotonic()
                self.play_index = 0
                self.mode = "playback"

                total_time = self.motion_slots[target_slot][-1]["t"] if self.motion_slots[target_slot] else 0.0
                print(f"\n[播放] 开始播放槽位 {target_slot + 1}，时长 {total_time:.3f}s，循环={'开' if self.PLAY_LOOP else '关'}")

                return result_js

            return self.blend_joint_states(self.transition_from_js, self.transition_to_js, alpha)

    def update_playback(self):
        with self.lock:
            if self.mode != "playback" or self.current_play_slot is None:
                return None

            sequence = self.motion_slots[self.current_play_slot]
            if not sequence:
                self.stop_playback_locked()
                return None

            if len(sequence) == 1:
                return deepcopy(sequence[0]["joint_states"])

            elapsed = time.monotonic() - self.play_start_time
            total_duration = sequence[-1]["t"]

            if total_duration <= 1e-9:
                return deepcopy(sequence[-1]["joint_states"])

            if elapsed > total_duration:
                if self.PLAY_LOOP:
                    elapsed = elapsed % total_duration
                    self.play_start_time = time.monotonic() - elapsed
                    self.play_index = 0
                else:
                    self.stop_playback_locked()
                    return None

            while self.play_index < len(sequence) - 1 and sequence[self.play_index + 1]["t"] < elapsed:
                self.play_index += 1

            while self.play_index > 0 and sequence[self.play_index]["t"] > elapsed:
                self.play_index -= 1

            i = self.play_index

            if i >= len(sequence) - 1:
                return deepcopy(sequence[-1]["joint_states"])

            frame_a = sequence[i]
            frame_b = sequence[i + 1]

            return self.interpolate_joint_states(frame_a, frame_b, elapsed)

    # =========================================================
    # 键盘监听
    # =========================================================
    def on_press(self, key):
        try:
            if key == keyboard.Key.esc:
                print("\n[系统] 收到退出指令")
                self.running = False
                return False

            if not hasattr(key, "char") or key.char is None:
                return

            ch = key.char.lower()

            if ch in self.record_keys:
                slot_idx = self.record_keys[ch]
                with self.lock:
                    if self.mode == "record" and self.current_record_slot == slot_idx:
                        need_stop = True
                    else:
                        need_stop = False

                if need_stop:
                    self.stop_record()
                else:
                    self.start_record(slot_idx)
                return

            if ch in self.play_keys:
                slot_idx = self.play_keys[ch]
                self.start_transition_to_slot(slot_idx)
                return

            if ch == "s":
                self.stop_all_actions()
                return

            if ch == "c":
                self.clear_last_slot()
                return

            if ch == "a":
                self.clear_all_slots()
                return

            if ch == "f":
                with self.lock:
                    if self.mode == "record":
                        self.stop_record_locked()
                    elif self.mode == "playback":
                        self.stop_playback_locked()
                    elif self.mode == "transition":
                        self.stop_transition_locked()
                    self.mode = "follow"
                print("\n[模式] 切换到跟随模式")
                return

        except Exception as e:
            print(f"\n[键盘监听异常] {e}")

    def keyboard_listener_thread(self):
        print("\n================ 键位说明 ================")
        print("录制槽位1~5: q / w / e / r / t   (按一次开始录制，再按一次停止录制)")
        print("播放槽位1~5: 1 / 2 / 3 / 4 / 5   (会先平滑过渡到目标动作开头，再开始播放)")
        print("停止录制/播放/过渡: s")
        print("清空最近操作槽: c")
        print("清空全部槽位: a")
        print("切回纯跟随模式: f")
        print("退出程序: Esc")
        print("=========================================\n")

        with keyboard.Listener(on_press=self.on_press) as listener:
            listener.join()

    # =========================================================
    # 主循环
    # =========================================================
    def run(self):
        self.setup_slaves()
        self.setup_master_arm()

        kb_thread = threading.Thread(target=self.keyboard_listener_thread, daemon=True)
        kb_thread.start()

        print("按 Ctrl+C 或 Esc 停止程序")
        print("=" * 120)

        update_interval = 1.0 / self.UPDATE_RATE
        frame_count = 0

        try:
            while self.running:
                loop_start = time.monotonic()

                try:
                    with self.lock:
                        mode_snapshot = self.mode

                    if mode_snapshot in ["follow", "record"]:
                        joint_states = self.robot_controller.get_fashionstar_joint_states()

                        if joint_states:
                            self.last_joint_states = deepcopy(joint_states)

                            self.send_joint_states_to_all_slaves(joint_states)

                            if mode_snapshot == "record":
                                self.update_recording(joint_states)

                            frame_count += 1

                    elif mode_snapshot == "transition":
                        transition_joint_states = self.update_transition()
                        if transition_joint_states:
                            self.send_joint_states_to_all_slaves(transition_joint_states)

                            frame_count += 1

                    elif mode_snapshot == "playback":
                        playback_joint_states = self.update_playback()
                        if playback_joint_states:
                            self.send_joint_states_to_all_slaves(playback_joint_states)

                            frame_count += 1

                    elapsed = time.monotonic() - loop_start
                    sleep_time = max(0.0, update_interval - elapsed)
                    time.sleep(sleep_time)

                except KeyboardInterrupt:
                    print("\n\n[系统] Ctrl+C 触发安全退出")
                    break

                except serial.SerialException as e:
                    print(f"\n\n❌ 致命错误：串口连接断开！{e}")
                    break

                except OSError as e:
                    print(f"\n\n❌ 致命错误：{e}")
                    break

                except Exception as e:
                    print(f"\n运行过程中出错: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(1.0)

        except KeyboardInterrupt:
            print("\n\n程序被用户中断")

        finally:
            self.cleanup()

    # =========================================================
    # 资源清理
    # =========================================================
    def cleanup(self):
        print("\n[系统] 正在清理资源...")

        self.running = False

        try:
            if self.robot_controller is not None:
                self.robot_controller.close()
        except Exception as e:
            print(f"[清理] 关闭主臂控制器失败: {e}")

        for slave in self.slaves:
            try:
                slave.safe_shutdown()
            except Exception as e:
                print(f"[清理] {slave.name} safe_shutdown失败: {e}")

            try:
                slave.close()
            except Exception as e:
                print(f"[清理] {slave.name} close失败: {e}")

        print("[系统] 程序已退出")


def main():
    controller = TeleopLooper()
    controller.run()


if __name__ == "__main__":
    main()
