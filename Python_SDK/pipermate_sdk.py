#!/usr/bin/env python3
"""
PiPER Mate与Piper机械臂集成控制
通过USB口连接PiPER Mate机械臂，读取其关节数据并控制Piper机械臂
"""

import math
import time
import serial
import argparse
from typing import List, Optional

# 导入PiPER_Mate SDK
from fashionstar_uart_sdk.uart_pocket_handler import (
    PortHandler as starai_PortHandler,
    SyncPositionControlOptions,
)

# rebot手臂关节角度限制(角度)
JOINT_ANGLE_LIMITS = {
    'joint1': [-150.0, 150.0],      # 角度限制
    'joint2': [-180.0,0.0],         
    'joint3': [-170.0, 0.0],        
    'joint4': [-80.0,80.0],      #<--- 这个关节的0.0限位改大即可低头
    'joint5': [-70.0, 70.0],        
    'joint6': [-120.0, 120.0],   
    'gripper':[-320, 0],
}

# 夹爪放缩比，rebot的夹爪会等比放大对应行程 须 >0 
GRIPPER_RATIO = 6



class PiPER_MateAgilex:
    """
    PiPER Mate与reBot机械臂集成控制类
    """
    

    
    def __init__(self,
                 fashionstar_port: str = "/dev/ttyUSB0",
                 piper_can_name: str = "can0",
                 gripper_exist: bool = True,
                 fashionstar_baud: int = 115200):
        """
        初始化PiPER Mate和rebot机械臂
        
        Args:
            fashionstar_port: PiPER Mate机械臂USB端口
            piper_can_name: Piper机械臂CAN端口名称
            gripper_exist: 是否包含夹爪
        """
        self.gripper_exist = gripper_exist
        
        # 初始化PiPER_Mate机械臂
        print(f"初始化PiPER_Mate机械臂，端口: {fashionstar_port}")
        try:
            self.fashionstar_handler = starai_PortHandler(fashionstar_port, fashionstar_baud)
            self.fashionstar_handler.openPort()
            print("PiPER_Mate机械臂连接成功")
        except Exception as e:
            print(f"PiPER_Mate机械臂连接失败: {e}")
            raise
        
        # 舵机配置
        self.servo_ids = [0, 1, 2, 3, 4, 5]  # 6个关节舵机
        if gripper_exist:
            self.servo_ids.append(6)  # 夹爪舵机
        
        # 清除圈数
        for servo_id in self.servo_ids:
            self.fashionstar_handler.write["Stop_On_Control_Mode"](servo_id, "unlocked", 900)
        self.fashionstar_handler.reset_multi_turn_angle(0xff)

        # 关节名称
        self.joint_names = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6']
        if gripper_exist:
            self.joint_names.append('gripper')
        
        # 初始化Piper机械臂

        
        # # 连接Piper机械臂
        # try:
        #     print("Piper机械臂连接成功")
        # except Exception as e:
        #     print(f"Piper机械臂连接失败: {e}")
        #     raise
        
        # # 设置Piper机械臂控制模式为关节控制模式
        # try:
        #     #此处初始化机械臂
        #     print("Piper机械臂控制模式设置成功")
        # except Exception as e:
        #     print(f"Piper机械臂控制模式设置失败: {e}")

        # print("PiPER_Mate与Piper机械臂集成控制初始化完成")
    
    def degrees_to_radians(self, degrees: float) -> float:
        """将角度转换为弧度"""
        return degrees * (math.pi / 180)
    
    def radians_to_degrees(self, radians: float) -> float:
        """将弧度转换为角度"""
        return radians * (180 / math.pi)
    
    def degrees_to_meters(self, degrees: float) -> float:
        """将夹爪角度转换为米（0-0.08m）"""
        return (degrees / 45.0) * 0.08
    
    def servoangle2jointstate(self, servo_id: int, servo_angle: float) -> float:
        """
        将PiPER_Mate舵机角度转换为Piper关节位置
        
        Args:
            servo_id: 舵机ID
            servo_angle: 舵机角度
            
        Returns:
            转换后的关节位置（弧度或米）
        """
        if servo_id in range(6):  # 手臂关节
            # 先对第1、4、6关节方向取反
            if servo_id in [0,1,5]:  # joint1, joint4, joint6
                servo_angle = -servo_angle
            
            # 根据关节名称获取角度限制
            joint_name = f'joint{servo_id + 1}'
            angle_limits = JOINT_ANGLE_LIMITS.get(joint_name, [-180.0, 180.0])
            
            # 对取反后的角度进行限制
            limited_angle = max(angle_limits[0], min(servo_angle, angle_limits[1]))
            
            # 转换为弧度
            return self.degrees_to_radians(limited_angle)
        elif servo_id == 6:
            #对角度取反
            servo_angle = -servo_angle*GRIPPER_RATIO
            if servo_angle > -14:
                servo_angle = 0 
            
            # 根据关节名称获取角度限制
            joint_name = f'gripper'
            angle_limits = JOINT_ANGLE_LIMITS.get(joint_name, [-180.0, 180.0])
            
            # 对取反后的角度进行限制
            limited_angle = max(angle_limits[0], min(servo_angle, angle_limits[1]))
            
            # 转换为弧度
            return self.degrees_to_radians(limited_angle)
        else:
            return 0.0
    
    def get_fashionstar_joint_states(self) -> dict:
        """
        读取PiPER_Mate机械臂的关节状态

        Returns:
            包含关节名称和对应位置的字典

        Raises:
            serial.SerialException: USB连接断开时抛出
            OSError: 当机械臂需要复位时抛出
        """
        try:
            # 同步读取所有舵机状态
            servos_id = {name: servo_id for name, servo_id in zip(self.joint_names, self.servo_ids)}
            monitor_data = self.fashionstar_handler.sync_read["Monitor"](servos_id)

            # 转换关节状态
            joint_states = {}
            for joint_name in self.joint_names:
                servo_id = servos_id[joint_name]
                servo_angle = monitor_data[joint_name].current_position
                joint_state = self.servoangle2jointstate(servo_id, servo_angle)
                joint_states[joint_name] = joint_state

            return joint_states

        except serial.SerialException as e:
            # USB连接断开，直接抛出异常
            raise
        except OSError as e:
            # 机械臂需要复位的错误，直接抛出
            raise
        except Exception as e:
            print(f"读取PiPER_Mate关节状态失败: {e}")
            return {}
    
    def control_piper_joints(self, joint_states: dict):
        """
        根据PiPER_Mate关节状态控制Piper机械臂
        
        Args:
            joint_states: 包含关节名称和对应位置的字典
        """
        try:
            # 提取关节角度（转换为Piper需要的0.001度单位）
            joint_angles = []
            for i in range(1, 7):  # joint1到joint6
                joint_name = f'joint{i}'
                if joint_name in joint_states:
                    # 将弧度转换为0.001度
                    radians = joint_states[joint_name]
                    degrees = self.radians_to_degrees(radians)
                    micro_degrees = int(degrees * 1000)  # 转换为0.001度
                    joint_angles.append(micro_degrees)
                else:
                    joint_angles.append(0)
            
            # 控制Piper机械臂关节
            if len(joint_angles) == 6:
                self.piper_interface.JointCtrl(
                    joint_angles[0],  # joint1
                    joint_angles[1],  # joint2
                    joint_angles[2],  # joint3
                    joint_angles[3],  # joint4
                    joint_angles[4],  # joint5
                    joint_angles[5]   # joint6
                )
            
            # # 控制Piper夹爪（如果存在）
            # if self.gripper_exist and 'gripper' in joint_states:
            #     # 将夹爪位置（米）转换为Piper需要的单位（微米，0.001mm）
            #     gripper_meters = joint_states['gripper']
            #     gripper_micrometers = int(gripper_meters * 1000 * 1000)  # 米 -> 毫米 -> 微米
            #     # 控制Piper夹爪
            #     # 参数：夹爪距离(微米), 夹爪力矩(0.001N/m), 控制码(0x01启用), 设置零点(0不设置)
            #     self.piper_interface.GripperCtrl(gripper_micrometers, 1000, 0x01, 0)
                
        except Exception as e:
            print(f"控制Piper机械臂失败: {e}")
    
    def enable_torque(self):
        """使能PiPER_Mate力矩"""
        try:
            # 使用锁定模式使能力矩
            for servo_id in self.servo_ids:
                self.fashionstar_handler.write["Stop_On_Control_Mode"](servo_id, "locked", 0)
            print("PiPER_Mate机械臂力矩已使能")
        except Exception as e:
            print(f"使能力矩失败: {e}")
    
    def disable_torque(self):
        """禁用PiPER_Mate力矩"""
        try:
            # 使用解锁模式禁用力矩
            for servo_id in self.servo_ids:
                self.fashionstar_handler.write["Stop_On_Control_Mode"](servo_id, "unlocked", 900)
            print("PiPER_Mate机械臂力矩已禁用")
        except Exception as e:
            print(f"禁用力矩失败: {e}")
    
    def get_piper_joint_states(self):
        """获取Piper机械臂的关节状态"""
        try:
            return self.piper_interface.GetArmJoint()
        except Exception as e:
            print(f"获取Piper关节状态失败: {e}")
            return None
    
    def close(self):
        """关闭连接"""
        print("\n关闭机械臂连接...")
        
        # 禁用PiPER_Mate力矩
        self.disable_torque()
        
        # # 关闭Piper连接
        # try:
        #     self.piper_interface.DisconnectPort()
        #     print("Piper机械臂连接已关闭")
        # except Exception as e:
        #     print(f"关闭Piper连接失败: {e}")
        
        # 关闭PiPER_Mate连接
        try:
            self.fashionstar_handler.closePort()
            print("PiPER_Mate机械臂连接已关闭")
        except Exception as e:
            print(f"关闭PiPER_Mate连接失败: {e}")
        
        print("所有连接已关闭")


# def main():
#     """主函数 - 预设参数，持续遥操作"""
    
#     # 预设参数 - 根据实际情况修改这些值
#     PIPERMATE_PORT = "/dev/ttyUSB0"    # PiPER_Mate USB端口
#     PIPER_CAN_NAME = "can0"              # Piper CAN端口
#     GRIPPER_EXIST = True                 # 是否包含夹爪
#     UPDATE_RATE = 100.0                  # 控制频率（Hz）- 可调节

#     Motor1=Motor(DM_Motor_Type.DM4310,0x01,0x11)
#     Motor2=Motor(DM_Motor_Type.DM4340,0x02,0x12)
#     Motor3=Motor(DM_Motor_Type.DM4340,0x03,0x13)
#     Motor4=Motor(DM_Motor_Type.DM4310,0x04,0x14)
#     Motor5=Motor(DM_Motor_Type.DM4310,0x05,0x15)
#     Motor6=Motor(DM_Motor_Type.DM4310,0x06,0x16)
#     # Motor7=Motor(DM_Motor_Type.DM4310,0x07,0x17)
#     serial_device = serial.Serial('/dev/ttyACM0', 921600, timeout=0.5)
#     MotorControl1=MotorControl(serial_device)
#     MotorControl1.addMotor(Motor1)
#     MotorControl1.addMotor(Motor2)
#     MotorControl1.addMotor(Motor3)
#     MotorControl1.addMotor(Motor4)
#     MotorControl1.addMotor(Motor5)
#     MotorControl1.addMotor(Motor6)
#     # MotorControl1.addMotor(Motor7)

#     if MotorControl1.switchControlMode(Motor1,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     if MotorControl1.switchControlMode(Motor2,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     if MotorControl1.switchControlMode(Motor3,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     if MotorControl1.switchControlMode(Motor4,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     if MotorControl1.switchControlMode(Motor5,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     if MotorControl1.switchControlMode(Motor6,Control_Type.POS_VEL):
#         print("switch POS_VEL success")
#     # if MotorControl1.switchControlMode(Motor7,Control_Type.POS_VEL):
#     #     print("switch POS_VEL success")





#     MotorControl1.save_motor_param(Motor1)
#     MotorControl1.save_motor_param(Motor2)
#     MotorControl1.save_motor_param(Motor3)
#     MotorControl1.save_motor_param(Motor4)
#     MotorControl1.save_motor_param(Motor5)
#     MotorControl1.save_motor_param(Motor6)
#     # MotorControl1.save_motor_param(Motor7)
#     MotorControl1.enable(Motor1)
#     MotorControl1.enable(Motor2)
#     MotorControl1.enable(Motor3)
#     MotorControl1.enable(Motor4)
#     MotorControl1.enable(Motor5)
#     MotorControl1.enable(Motor6)
#     # MotorControl1.enable(Motor7)

#     robot_controller = None
#     try:
#         # 创建机械臂控制器
#         robot_controller = PiPER_MateAgilex(
#             fashionstar_port=PIPERMATE_PORT,
#             piper_can_name=PIPER_CAN_NAME,
#             gripper_exist=GRIPPER_EXIST
#         )
#         # 开始持续遥操作
#         print(f"\n开始PiPER_Mate控制Piper,控制频率{UPDATE_RATE}Hz...")
#         print("按 Ctrl+C 停止遥操作")
#         print("=" * 120)
        
#         # 持续遥操作循环
#         update_interval = 1.0 / UPDATE_RATE
#         frame_count = 0
        
#         while True:
#             try:
#                 # 读取PiPER_Mate关节状态
#                 joint_states = robot_controller.get_fashionstar_joint_states()
                
#                 if joint_states:
#                     # 控制Piper机械臂
                    
#                     # MotorControl1.control_Pos_Vel(Motor1,joint_states["joint1"],10)
#                     MotorControl1.control_Pos_Vel(Motor2,joint_states["joint2"],10)
#                     MotorControl1.control_Pos_Vel(Motor3,joint_states["joint3"],10)
#                     MotorControl1.control_Pos_Vel(Motor4,joint_states["joint4"],10)
#                     MotorControl1.control_Pos_Vel(Motor5,joint_states["joint5"],10)
#                     MotorControl1.control_Pos_Vel(Motor6,joint_states["joint6"],10)
#                     # MotorControl1.control_Pos_Vel(Motor7,joint_states["gripper"],30)

#                     # 实时显示关节状态（每10帧显示一次，避免刷屏）
#                     frame_count += 1
#                     if frame_count % 10 == 0:
#                         print("\rpiper当前关节状态:", end="")
#                         for joint, state in joint_states.items():
#                             print(f" {joint}:{state:.4f}", end="")
#                         print("   ", end="", flush=True)
                
#                 # 等待下一个更新周期
#                 time.sleep(update_interval)
                
#             except KeyboardInterrupt:
#                 print("\n\n用户手动停止遥操作")
#                 break
#             # 核心：捕获USB断开异常，立即终止程序
#             except serial.SerialException as e:
#                 print(f"\n\n❌ 致命错误：PiPER_Mate USB连接断开！{e}")
#                 break
#             # 捕获机械臂复位错误，立即终止程序
#             except OSError as e:
#                 print(f"\n\n❌ 致命错误：{e}")
#                 break
#             except Exception as e:
#                 print(f"\n遥操作过程中出错: {e}")
#                 import traceback
#                 traceback.print_exc()
#                 time.sleep(1.0)  # 非致命错误，等待1秒继续
        
#     except KeyboardInterrupt:
#         print("\n\n程序被用户中断")
#     except serial.SerialException as e:
#         print(f"\n\n❌ 程序启动失败：PiPER_Mate USB端口连接失败！{e}")
#     except OSError as e:
#         print(f"\n\n❌ 程序启动失败：{e}")
#     except Exception as e:
#         print(f"\n程序运行出错: {e}")
#         import traceback
#         traceback.print_exc()
#     finally:
#         # 确保连接被正确关闭
#         if robot_controller is not None:
#             robot_controller.close()


if __name__ == "__main__":
    print("没有案例，请运行rebot_pipermate.py")
#     main()