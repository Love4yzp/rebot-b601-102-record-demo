# rebot b601-DM & rebot 102 demo

主从臂示教 + 录制 / 回放 demo。

> **系统支持**：macOS / Linux。键盘监听基于 POSIX `termios`，**不支持 Windows**。

---

## 注意

1. `pipermate_sdk.py` 可配置 rebot 的最大行程，夹爪和操控器的放缩比（必须为正）

---

## 🚀 快速开始

### rebot 设置

1. 启动前将所有关节置于 0 位，包括夹爪
2. 夹爪电机设置为带电流限制的位控，如果夹持力不够，代码里设置参数

### 安装步骤

需要 Python 3.10+。

```bash
# 1. 安装依赖
sudo apt update
pip install pyserial fashionstar-uart-sdk scipy numpy

# 或者用 uv（推荐）
uv sync

# 2. 运行程序
sudo chmod 666 /dev/ttyUSB*
sudo chmod 666 /dev/ttyACM*
python3 ./Python_SDK/rebot_so102_record.py
```

启动后会自动识别主从臂串口，无需手动改代码。

![Screenshot](Screenshot%20from%202026-03-23%2000-12-55.png)

---

## ✨ 特性

### 自动识别串口

不再硬编码 `/dev/ttyUSB0`、`/dev/ttyACM0`。启动时枚举所有 USB 串口，按 VID/PID/manufacturer 识别主从臂；同机器接了其它 USB 串口设备也不会误选，多候选时会让你输入编号选择。

### 支持 SSH / headless 运行

键盘监听基于 `termios + select` cbreak 模式，不依赖图形环境，可以直接 `ssh` 进设备运行：

- `Ctrl+C` 仍可立即中断
- 退出键支持 `Esc` 或 `Ctrl+C`
- stdin 不是 tty 时（例如通过管道运行）会自动降级，仅靠 `Ctrl+C` 退出

### 录制槽位自动持久化

录制 / 清空时自动同步到 `recordings/slot_<N>.json`（原子写入），启动时自动加载，重启后不丢失，无需重新示教。

---

## ⌨️ 键位说明

| 键位             | 动作                      |
|------------------|---------------------------|
| `1`–`6`          | 录制 / 停止录制对应槽位   |
| `q w e r t y`    | 播放对应槽位的录制        |
| `s`              | 停止当前播放              |
| `c`              | 清空最近一次录制的槽位    |
| `a`              | 清空全部槽位              |
| `f`              | 切回纯跟随模式            |
| `Esc` / `Ctrl+C` | 退出程序                  |

---

## ⚠️ 安全注意事项

**急停控制**：程序运行时按 `Ctrl+C` 可立即停止

---

## 常见问题

**Q1: 找不到 `/dev/ttyUSB0` 设备？**

```bash
# 检查 USB 设备
ls -l /dev/ttyUSB* /dev/ttyACM*

# 检查 CH340 驱动
lsusb | grep CH340

# 尝试卸载 brltty（大概率）
sudo apt remove brltty
```

启动时程序会打印枚举到的所有串口及其 VID/PID/manufacturer，便于排错。

**Q2: 找不到主臂或从臂串口？**

如果同一类设备有多个候选，程序会让你输入编号选择。否则请确认 USB 线和电源已连好。

**Q3: 机械臂连接失败？**

- 检查 USB 线连接是否松动
- 确认机械臂电源已开启
- 检查驱动板开关位置（应拨向电源接口一侧）
- 尝试更换 USB 端口

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
