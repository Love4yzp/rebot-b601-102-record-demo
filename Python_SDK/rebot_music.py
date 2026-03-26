from pipermate_sdk import PiPER_MateAgilex
import time
import serial
import threading
from copy import deepcopy
from pynput import keyboard
from u2can.DM_CAN import *

# 导入PiPER_Mate SDK
from fashionstar_uart_sdk.uart_pocket_handler import (
    PortHandler as starai_PortHandler,
    SyncPositionControlOptions,
)


class TeleopLooper:
    """
    功能：
    1. 主从臂实时跟随
    2. 录制动作序列（保留原始时间间隔）
    3. 播放动作序列（循环播放）
    4. 支持多个动作槽
    5. 支持停止 / 清空
    """

    def __init__(self):
        # =========================
        # 预设参数
        # =========================
        self.PIPERMATE_PORT = "/dev/ttyUSB0"      # 主臂端口
        self.SLAVE_SERIAL_PORT = "/dev/ttyACM0"   # 从臂CAN串口
        self.BAUDRATE = 921600
        self.GRIPPER_EXIST = True
        self.UPDATE_RATE = 200

        # 回放是否循环
        self.PLAY_LOOP = True

        # 动作槽数量
        self.NUM_SLOTS = 5

        # 键位映射
        # r/t/y/u/i -> 录制到槽位1~5（按一次开始，再按一次结束）
        # 1/2/3/4/5 -> 播放槽位1~5
        # s -> 停止当前录制或播放
        # c -> 清空当前播放/最近操作槽
        # a -> 清空全部槽位
        # esc -> 退出程序
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
        self.lock = threading.Lock()

        # 模式：
        # "idle"      空闲
        # "follow"    单纯跟随
        # "record"    跟随 + 录制
        # "playback"  脱离主臂，播放录制动作
        self.mode = "follow"

        # 动作槽
        # 每个槽位保存:
        # [
        #   {"t": 相对时间秒, "joint_states": {...}},
        #   ...
        # ]
        self.motion_slots = [[] for _ in range(self.NUM_SLOTS)]

        self.current_record_slot = None
        self.current_play_slot = None
        self.last_operated_slot = None

        self.record_start_time = None
        self.play_start_time = None
        self.play_index = 0

        # 设备对象
        self.serial_device = None
        self.robot_controller = None
        self.MotorControl1 = None
        self.motors = []

        # 上一次发送的状态（可用于避免空值）
        self.last_joint_states = None

    # =========================================================
    # 设备初始化
    # =========================================================
    def setup_motors(self):
        self.serial_device = serial.Serial(
            self.SLAVE_SERIAL_PORT,
            self.BAUDRATE,
            timeout=0.5
        )

        Motor1 = Motor(DM_Motor_Type.DM4340, 0x01, 0x11)
        Motor2 = Motor(DM_Motor_Type.DM4340, 0x02, 0x12)
        Motor3 = Motor(DM_Motor_Type.DM4340, 0x03, 0x13)
        Motor4 = Motor(DM_Motor_Type.DM4310, 0x04, 0x14)
        Motor5 = Motor(DM_Motor_Type.DM4310, 0x05, 0x15)
        Motor6 = Motor(DM_Motor_Type.DM4310, 0x06, 0x16)
        Motor7 = Motor(DM_Motor_Type.DM4310, 0x07, 0x17)

        self.MotorControl1 = MotorControl(self.serial_device)
        self.MotorControl1.addMotor(Motor1)
        self.MotorControl1.addMotor(Motor2)
        self.MotorControl1.addMotor(Motor3)
        self.MotorControl1.addMotor(Motor4)
        self.MotorControl1.addMotor(Motor5)
        self.MotorControl1.addMotor(Motor6)
        self.MotorControl1.addMotor(Motor7)

        self.motors = [Motor1, Motor2, Motor3, Motor4, Motor5, Motor6, Motor7]

        for motor in self.motors:
            self.MotorControl1.enable(motor)
            time.sleep(0.001)

    def setup_master_arm(self):
        self.robot_controller = PiPER_MateAgilex(
            fashionstar_port=self.PIPERMATE_PORT,
            gripper_exist=self.GRIPPER_EXIST
        )

    # =========================================================
    # 从臂发送控制
    # =========================================================
    def send_joint_states_to_slave(self, joint_states):
        """
        将关节状态发送给从臂
        """
        try:
            self.MotorControl1.control_Pos_Vel(self.motors[0], joint_states["joint1"], 30)
            time.sleep(0.0005)
            self.MotorControl1.control_Pos_Vel(self.motors[1], joint_states["joint2"], 30)
            time.sleep(0.0005)
            self.MotorControl1.control_Pos_Vel(self.motors[2], joint_states["joint3"], 30)
            time.sleep(0.0005)
            self.MotorControl1.control_Pos_Vel(self.motors[3], joint_states["joint4"], 30)
            time.sleep(0.0005)
            self.MotorControl1.control_Pos_Vel(self.motors[4], joint_states["joint5"], 30)
            time.sleep(0.0005)
            self.MotorControl1.control_Pos_Vel(self.motors[5], joint_states["joint6"], 30)
            time.sleep(0.0005)

            # 夹爪
            self.MotorControl1.control_pos_force(
                self.motors[6],
                joint_states["gripper"],
                2000,
                350
            )
            time.sleep(0.0005)

        except Exception as e:
            print(f"\n发送从臂控制失败: {e}")
            raise
    def interpolate_joint_states(self, frame_a, frame_b, t_now):
        """
        对两个录制帧之间做线性插值

        参数:
            frame_a: {"t": ..., "joint_states": {...}}
            frame_b: {"t": ..., "joint_states": {...}}
            t_now: 当前相对播放时间

        返回:
            插值后的 joint_states 字典
        """
        t0 = frame_a["t"]
        t1 = frame_b["t"]
        js0 = frame_a["joint_states"]
        js1 = frame_b["joint_states"]

        # 防止除零
        if abs(t1 - t0) < 1e-9:
            return deepcopy(js0)

        alpha = (t_now - t0) / (t1 - t0)
        alpha = max(0.0, min(1.0, alpha))

        # ⭐ SmoothStep
        alpha = alpha * alpha * (3 - 2 * alpha)

        # 限幅，避免数值越界
        if alpha < 0.0:
            alpha = 0.0
        elif alpha > 1.0:
            alpha = 1.0

        interpolated = {}
        for joint in js0.keys():
            interpolated[joint] = js0[joint] + alpha * (js1[joint] - js0[joint])

        return interpolated
    # =========================================================
    # 录制 / 播放 控制
    # =========================================================
    def start_record(self, slot_idx):
        with self.lock:
            # 如果正在播放，先停掉
            if self.mode == "playback":
                self.stop_playback_locked()

            self.motion_slots[slot_idx] = []
            self.current_record_slot = slot_idx
            self.last_operated_slot = slot_idx
            self.record_start_time = time.monotonic()
            self.mode = "record"

            print(f"\n[录制] 开始录制槽位 {slot_idx + 1}")

    def stop_record(self):
        with self.lock:
            if self.mode != "record":
                return

            slot_idx = self.current_record_slot
            frame_num = len(self.motion_slots[slot_idx])

            self.current_record_slot = None
            self.record_start_time = None
            self.mode = "follow"

            print(f"\n[录制] 停止录制槽位 {slot_idx + 1}，共记录 {frame_num} 帧")

    def start_playback(self, slot_idx):
        with self.lock:
            if len(self.motion_slots[slot_idx]) == 0:
                print(f"\n[播放] 槽位 {slot_idx + 1} 没有录制内容")
                return

            # 如果在录制，先结束录制
            if self.mode == "record":
                self.stop_record_locked()

            self.current_play_slot = slot_idx
            self.last_operated_slot = slot_idx
            self.play_start_time = time.monotonic()
            self.play_index = 0
            self.mode = "playback"

            total_time = self.motion_slots[slot_idx][-1]["t"] if self.motion_slots[slot_idx] else 0.0
            print(f"\n[播放] 开始播放槽位 {slot_idx + 1}，时长 {total_time:.3f}s，循环={'开' if self.PLAY_LOOP else '关'}")

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

    def stop_record_locked(self):
        slot_idx = self.current_record_slot
        frame_num = len(self.motion_slots[slot_idx]) if slot_idx is not None else 0
        self.current_record_slot = None
        self.record_start_time = None
        self.mode = "follow"
        print(f"\n[录制] 停止录制槽位 {slot_idx + 1 if slot_idx is not None else '?'}，共记录 {frame_num} 帧")

    def stop_all_actions(self):
        with self.lock:
            if self.mode == "record":
                self.stop_record_locked()
            elif self.mode == "playback":
                self.stop_playback_locked()
            else:
                print("\n[停止] 当前没有录制或播放任务")

    def clear_slot(self, slot_idx):
        with self.lock:
            # 如果正在播放/录制这个槽位，先停
            if self.mode == "record" and self.current_record_slot == slot_idx:
                self.stop_record_locked()
            if self.mode == "playback" and self.current_play_slot == slot_idx:
                self.stop_playback_locked()

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

            for i in range(self.NUM_SLOTS):
                self.motion_slots[i] = []

            print("\n[清空] 已清空所有动作槽位")

    # =========================================================
    # 录制 / 播放 更新
    # =========================================================
    def update_recording(self, joint_states):
        with self.lock:
            if self.mode != "record" or self.current_record_slot is None:
                return

            t_rel = time.monotonic() - self.record_start_time
            self.motion_slots[self.current_record_slot].append({
                "t": t_rel,
                "joint_states": deepcopy(joint_states)
            })

    def update_playback(self):
        """
        按原始时间戳回放，并对相邻关键帧做线性插值，
        保证动作节奏一致，同时让轨迹更平滑
        """
        with self.lock:
            if self.mode != "playback" or self.current_play_slot is None:
                return None

            sequence = self.motion_slots[self.current_play_slot]
            if not sequence:
                self.stop_playback_locked()
                return None

            # 只有1帧，直接发这一帧
            if len(sequence) == 1:
                return deepcopy(sequence[0]["joint_states"])

            elapsed = time.monotonic() - self.play_start_time
            total_duration = sequence[-1]["t"]

            # 播放结束处理
            if elapsed > total_duration:
                if self.PLAY_LOOP:
                    # 循环模式：把 elapsed 映射回动作周期内
                    elapsed = elapsed % total_duration if total_duration > 1e-9 else 0.0
                    self.play_start_time = time.monotonic() - elapsed
                    self.play_index = 0
                else:
                    self.stop_playback_locked()
                    return None

            # 找到当前时间所在区间 [sequence[i], sequence[i+1]]
            while self.play_index < len(sequence) - 1 and sequence[self.play_index + 1]["t"] < elapsed:
                self.play_index += 1

            i = self.play_index

            # 边界保护
            if i >= len(sequence) - 1:
                return deepcopy(sequence[-1]["joint_states"])

            frame_a = sequence[i]
            frame_b = sequence[i + 1]

            # 如果 elapsed 比当前 frame_a 还小，向前修正
            while i > 0 and sequence[i]["t"] > elapsed:
                i -= 1
                self.play_index = i
                frame_a = sequence[i]
                frame_b = sequence[i + 1]

            interpolated_joint_states = self.interpolate_joint_states(frame_a, frame_b, elapsed)
            return interpolated_joint_states
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

            # 录制键：按一次开始，再按一次结束
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

            # 播放键
            if ch in self.play_keys:
                slot_idx = self.play_keys[ch]
                self.start_playback(slot_idx)
                return

            # 停止键
            if ch == "s":
                self.stop_all_actions()
                return

            # 清空最近操作槽
            if ch == "c":
                self.clear_last_slot()
                return

            # 清空全部
            if ch == "a":
                self.clear_all_slots()
                return

            # 单纯切回跟随模式
            if ch == "f":
                with self.lock:
                    if self.mode == "record":
                        self.stop_record_locked()
                    elif self.mode == "playback":
                        self.stop_playback_locked()
                    self.mode = "follow"
                print("\n[模式] 切换到跟随模式")
                return

        except Exception as e:
            print(f"\n[键盘监听异常] {e}")

    def keyboard_listener_thread(self):
        print("\n================ 键位说明 ================")
        print("录制槽位1~5: q / w / e / r / t   (按一次开始录制，再按一次停止录制)")
        print("播放槽位1~5: 1 / 2 / 3 / 4 / 5")
        print("停止录制/播放: s")
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
        self.setup_motors()
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
                    mode_snapshot = None
                    with self.lock:
                        mode_snapshot = self.mode

                    # 1) 跟随 / 录制模式：读取主臂并驱动从臂
                    if mode_snapshot in ["follow", "record"]:
                        joint_states = self.robot_controller.get_fashionstar_joint_states()

                        if joint_states:
                            self.last_joint_states = deepcopy(joint_states)

                            # 发给从臂
                            self.send_joint_states_to_slave(joint_states)

                            # 如果在录制，保存带时间戳的数据
                            if mode_snapshot == "record":
                                self.update_recording(joint_states)

                            frame_count += 1
                            if frame_count % 10 == 0:
                                print("\r[跟随] 当前关节状态:", end="")
                                for joint, state in joint_states.items():
                                    print(f" {joint}:{state:.4f}", end="")
                                print("   ", end="", flush=True)

                    # 2) 回放模式：不读取主臂，只按时间序列回放
                    elif mode_snapshot == "playback":
                        playback_joint_states = self.update_playback()
                        if playback_joint_states:
                            self.send_joint_states_to_slave(playback_joint_states)

                            frame_count += 1
                            if frame_count % 10 == 0:
                                #print("\r[播放] 当前回放状态:", end="")
                                for joint, state in playback_joint_states.items():
                                    print(f" {joint}:{state:.4f}", end="")
                                print("   ", end="", flush=True)

                    # 保持固定更新率
                    elapsed = time.monotonic() - loop_start
                    sleep_time = max(0.0, update_interval - elapsed)
                    time.sleep(sleep_time)

                except KeyboardInterrupt:
                    print("\n\n用户手动停止程序")
                    break

                # 核心：捕获USB断开异常，立即终止程序
                except serial.SerialException as e:
                    print(f"\n\n❌ 致命错误：串口连接断开！{e}")
                    break

                # 捕获机械臂复位错误，立即终止程序
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

        try:
            if self.serial_device is not None and self.serial_device.is_open:
                self.serial_device.close()
        except Exception as e:
            print(f"[清理] 关闭串口失败: {e}")

        print("[系统] 程序已退出")


def main():
    controller = TeleopLooper()
    controller.run()


if __name__ == "__main__":
    main()
