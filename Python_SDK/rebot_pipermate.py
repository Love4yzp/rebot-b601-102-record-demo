from pipermate_sdk import PiPER_MateAgilex
import time
import serial
from u2can.DM_CAN import *

# 导入PiPER_Mate SDK
from fashionstar_uart_sdk.uart_pocket_handler import (
    PortHandler as starai_PortHandler,
    SyncPositionControlOptions,
)




def main():
    """主函数 - 预设参数，持续遥操作"""
    
    # 预设参数 - 根据实际情况修改这些值
    PIPERMATE_PORT = "COM8"    # PiPER_Mate USB端口
    serial_device = serial.Serial('COM3', 921600, timeout=0.5)



    GRIPPER_EXIST = True                
    UPDATE_RATE = 80.0                  

    Motor1=Motor(DM_Motor_Type.DM4340,0x01,0x11)
    Motor2=Motor(DM_Motor_Type.DM4340,0x02,0x12)
    Motor3=Motor(DM_Motor_Type.DM4340,0x03,0x13)
    Motor4=Motor(DM_Motor_Type.DM4310,0x04,0x14)
    Motor5=Motor(DM_Motor_Type.DM4310,0x05,0x15)
    Motor6=Motor(DM_Motor_Type.DM4310,0x06,0x16)
    Motor7=Motor(DM_Motor_Type.DM4310,0x07,0x17)
    MotorControl1=MotorControl(serial_device)
    MotorControl1.addMotor(Motor1)
    MotorControl1.addMotor(Motor2)
    MotorControl1.addMotor(Motor3)
    MotorControl1.addMotor(Motor4)
    MotorControl1.addMotor(Motor5)
    MotorControl1.addMotor(Motor6)
    MotorControl1.addMotor(Motor7)


    motors = [Motor1, Motor2, Motor3, Motor4, Motor5, Motor6,Motor7]


    for motor in motors:
        MotorControl1.disable(motor)
        if motor != Motor7:
            MotorControl1.switchControlMode(motor,Control_Type.POS_VEL)
        else:
            MotorControl1.switchControlMode(motor,Control_Type.Torque_Pos)
        MotorControl1.enable(motor)
        time.sleep(0.001)



    robot_controller = None
    try:
        # 创建机械臂控制器
        robot_controller = PiPER_MateAgilex(
            fashionstar_port=PIPERMATE_PORT,
            gripper_exist=GRIPPER_EXIST
        )
        # 开始持续遥操作
        print("按 Ctrl+C 停止遥操作")
        print("=" * 120)
        
        # 持续遥操作循环
        update_interval = 1.0 / UPDATE_RATE
        frame_count = 0
        
        while True:
            try:
                # 读取PiPER_Mate关节状态z
                joint_states = robot_controller.get_fashionstar_joint_states()
                
                if joint_states:
                    # 控制Piper机械臂
                    
                    MotorControl1.control_Pos_Vel(Motor1,joint_states["joint1"],25)

                    MotorControl1.control_Pos_Vel(Motor2,joint_states["joint2"],25)

                    MotorControl1.control_Pos_Vel(Motor3,joint_states["joint3"],25)

                    MotorControl1.control_Pos_Vel(Motor4,joint_states["joint4"],25)
                    time.sleep(0.002)
                    MotorControl1.control_Pos_Vel(Motor5,joint_states["joint5"],25)

                    MotorControl1.control_Pos_Vel(Motor6,joint_states["joint6"],25)


                    MotorControl1.control_pos_force(Motor7,joint_states["gripper"],2000,500)#爪子 速度*100 百分比电流10000
                    time.sleep(0.002)
                    # 实时显示关节状态（每10帧显示一次，避免刷屏）
                    frame_count += 1
                    if frame_count % 10 == 0:
                        print("\rpiper当前关节状态:", end="")
                        for joint, state in joint_states.items():
                            print(f" {joint}:{state:.4f}", end="")
                        print("   ", end="", flush=True)
                
                # 等待下一个更新周期
                time.sleep(update_interval)
                
            except KeyboardInterrupt:
                print("\n\n用户手动停止遥操作")
                # MotorControl1.disable(Motor7)
                # MotorControl1.control_Pos_Vel(Motor1,0,0.4)
                # time.sleep(0.002)
                # MotorControl1.control_Pos_Vel(Motor2,0,0.4)
                # time.sleep(0.002)
                # MotorControl1.control_Pos_Vel(Motor3,0,0.4)
                # time.sleep(0.002)
                # MotorControl1.control_Pos_Vel(Motor4,0,0.4)
                # time.sleep(0.002)
                # MotorControl1.control_Pos_Vel(Motor5,0,0.4)
                # time.sleep(0.002)
                # MotorControl1.control_Pos_Vel(Motor6,0,0.4)
                # print("\n\n执行8S复位流程")
                # time.sleep(8)
                # for motor in motors:
                #     MotorControl1.disable(motor)
                #     time.sleep(0.001)
                # print("\n\n失能完成")
                break
            # 核心：捕获USB断开异常，立即终止程序
            except serial.SerialException as e:
                print(f"\n\n❌ 致命错误：PiPER_Mate USB连接断开！{e}")
                break
            # 捕获机械臂复位错误，立即终止程序
            except OSError as e:
                print(f"\n\n❌ 致命错误：{e}")
                break
            except Exception as e:
                print(f"\n遥操作过程中出错: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1.0)  # 非致命错误，等待1秒继续
        
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    except serial.SerialException as e:
        print(f"\n\n❌ 程序启动失败：PiPER_Mate USB端口连接失败！{e}")
    except OSError as e:
        print(f"\n\n❌ 程序启动失败：{e}")
    except Exception as e:
        print(f"\n程序运行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 确保连接被正确关闭
        if robot_controller is not None:
            robot_controller.close()


if __name__ == "__main__":
    main()