# PiPER-Mate

---

## 注意

1.pipermate_sdk.py可配置rebot的最大行程，夹爪和操控器的放缩比（必须为正）

---

## 🚀 快速开始



### rebot设置


1.启动前将所有关节置于0位，包括夹爪
2.夹爪电机设置为带电流限制的位控，如果夹持力不够，代码里设置参数






### 安装步骤

Python SDK

```bash
# 1. 安装依赖
#达秒电机库相关依赖是serial , numpy 这几个库，记得安装相关依赖。
sudo apt update
pip install pyserial fashionstar-uart-sdk scipy numpy 


# 2. 运行程序
sudo chmod 666 /dev/ttyUSB0
sudo chmod 666 /dev/ttyACM0
python3 ./Python_SDK/rebot_so102_record.py
```

![Screenshot](Screenshot%20from%202026-03-23%2000-12-55.png)


## ⚠️ 安全注意事项
**急停控制**：程序运行时按 `Ctrl+C` 可立即停止
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

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

