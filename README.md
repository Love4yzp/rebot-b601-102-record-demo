# PiPER-Mate

文档待更新

![Programming Language](https://img.shields.io/badge/language-Python-blue?style=flat-square)
![Framework](https://img.shields.io/badge/framework-ROS2%20Humble-orange?style=flat-square)
![Hardware](https://img.shields.io/badge/hardware-PiPER%20Mate%20%2B%20Piper-green?style=flat-square)
![OS](https://img.shields.io/badge/OS-Ubuntu%2022.04-purple?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)

---

## 注意

1.当夹爪跳齿后，设置最小值为0点，默认最大行程值为-320（方向为负）
2.1号关节pid调的很小，>50%行程运动可能会抖动
3.pipermate_sdk.py可配置rebot的最大行程，夹爪和操控器的放缩比（必须为正）

---

## 🚀 快速开始



### rebot设置


1.全部关节电机设置控制模式为位置速度
2.夹爪电机设置为MIT，或者直接改code
3.MotorControl1.controlMIT(Motor7, 5, 1,joint_states["gripper"],1,0)





### 安装步骤

Python SDK

```bash
# 1. 安装依赖
#达秒电机库相关依赖是serial , numpy 这几个库，记得安装相关依赖。
sudo apt update
pip install pyserial fashionstar-uart-sdk scipy numpy 


# 2. 运行程序
sudo chmod 777 /dev/ttyUSB*
sudo chmod 777 /dev/ttyA*
python3 ./Python_SDK/rebot_pipermate.py
```



## 📂 项目结构

```bash
PiPER-Mate/
├── Python_SDK/                  # Python SDK控制方式
│   ├── u2can/                   # 达秒驱动
│   ├── rebot_pipermate.py       # 主控制程序
│   └── README.md                # 详细使用文档
└── README.md                    # 本文档

```

## 📊 关节映射

系统自动将 PiPER Mate 的 6 个关节映射到 Piper 机械臂：

| 关节 | PiPER Mate 角度 | Piper 弧度 | 方向 |
|------|------------------|------------|------|
| Joint1 | -150° ~ 150° | -2.62 ~ 2.62 rad | 反向 |
| Joint2 | 0° ~ 180° | 0 ~ 3.14 rad | 正向 |
| Joint3 | -170° ~ 0° | -2.97 ~ 0 rad | 正向 |
| Joint4 | -100° ~ 100° | -1.75 ~ 1.75 rad | 反向 |
| Joint5 | -70° ~ 70° | -1.22 ~ 1.22 rad | 正向 |
| Joint6 | -120° ~ 120° | -2.09 ~ 2.09 rad | 反向 |

---

## ⚠️ 安全注意事项
2. **急停控制**：程序运行时按 `Ctrl+C` 可立即停止
---



## 常见问题

**Q1: 找不到 `/dev/ttyUSB0` 设备？**

```bash
# 检查USB设备
ls -l /dev/ttyUSB*

# 检查CH340驱动
lsusb | grep CH340

# 尝试卸载brltty（大概率）
sudo apt remove brltty


# 如果没有安装驱动，请从官网下载安装
```



**Q3: 机械臂连接失败？**

- 检查USB线连接是否松动
- 确认机械臂电源已开启
- 检查驱动板开关位置（应拨向电源接口一侧）
- 尝试更换USB端口

**Q4: USB连接断开时程序不终止？**

程序已添加异常处理，当PiPER Mate USB断开时会自动终止并显示错误信息：

```bash
❌ 致命错误：PiPER Mate USB连接断开！
```

---

## 📖 详细文档

选择你需要的控制方式查看详细文档：

- 📘 **[Python SDK 详细文档](./Python_SDK/README.md)** - 推荐！最简单易用
- 📗 **[ROS2 HUMBLE 详细文档](./ROS2_HUMBLE/README.md)** - 适用于机器人系统集成
- 📙 **[Lerobot 详细文档](./Lerobot/README.md)** - 适用于AI训练和研究

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

