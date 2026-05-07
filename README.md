# rebot-record

主臂（B601-DM）→ 从臂（SO102）遥操、录制、回放的常驻服务。
浏览器即客户端：装好之后，机器人主机开机自启，运维人员从局域网内任何电脑打开网页就能用。

> **Linux + Docker**。Web UI 跨平台（任何浏览器）。

---

## 功能

- **跟随**（默认）：主臂 → 从臂 30Hz 遥操
- **录制**：在跟随的同时把动作存进动作库（动态数量、可命名、不限 5 槽）
- **回放（Loop）**：循环播放某个动作
- **回放（执行一次）**：播放一遍后，**慢慢**回到主臂当前姿态再回到跟随
- **常驻**：systemd-style 自动重启，USB 拔插自动恢复
- **Web UI**：模式驱动的单页面板（关节遥测 + 录制/回放控制 + 动作库），不同模式整屏切色 + 大计时器 + 圆形停止键

---

## 快速部署

### 1. 检查硬件 & udev majors

部署机上确认 USB 设备 char major 号（影响 docker 的 `device_cgroup_rules`）：

```bash
ls -l /dev/ttyUSB0 /dev/ttyACM0
# 输出形如 "crw-rw---- 1 root dialout 188, 0 ..." → 188 是 CH340
#                                       "166, 0 ..." → 166 是 CDC ACM
```

CH340（B601-DM 主臂）一般是 188，HDSC CDC（SO102 从臂）一般是 166。
如果你的内核不同，编辑 `deploy/docker-compose.yml` 里的 `device_cgroup_rules`。

### 2. 启动

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml logs -f
```

第一次构建需要几分钟（npm + uv sync）。之后 `up -d` 秒级。

### 3. 打开 Web UI

任意 LAN 内电脑浏览器：

```
http://<部署机IP>:8000
```

---

## 使用流程

1. 默认就是 **跟随** 模式（顶部淡灰，左侧关节条绿色）—— 主臂动，从臂跟。
2. 想录一段动作：
   - 起始位置摆好（或者就用主臂当前位置）
   - 输入动作名（可留空，默认 "Action N"）→ **开始录制**
   - 顶部 banner 整条变红、关节条变红、中央换成大计时器 + 帧数 + 圆形停止键
   - **停止录制**（点圆形停止键）→ 自动回 follow，新动作出现在右侧列表里
3. 想回放：在右侧动作库点对应行
   - **循环**：banner 黄(transition 0.6s) → 蓝(playback)，会一直跑直到再点圆形停止键
   - **执行**：播一遍，末尾走灰色 return_to_follow 阶段，**慢慢**滑回主臂当前位置（默认 2s）后回到跟随
4. 改名：直接点动作名字（inline 编辑，Enter 提交 / Esc 取消 / 失焦自动保存）
5. 删除：点"删除"变红"确认删除"，2.5s 内再点一次才生效（防误删）
6. 老动作多了找不到：右上角"搜索全部"打开覆盖式弹窗，支持名称搜索 + 按最近/名称/时长排序

回放进行中可以随时点圆形停止键切回跟随。

---

## 架构

```
┌──────────────────────────────────────────────┐
│ Browser (任何 LAN 内电脑)                    │
│  └─ React + Tailwind SPA (mode-driven UI)    │
│       │ HTTP REST + WebSocket                │
└───────┼──────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────┐
│ Container: rebot-record                      │
│  ├─ FastAPI (uvicorn)                        │
│  │   ├─ /api/*  REST                         │
│  │   ├─ /ws     state push @10Hz             │
│  │   └─ /       静态前端                     │
│  └─ Controller thread (30Hz)                 │
│       ├─ master read (CH340 /dev/ttyUSB*)    │
│       └─ slave write (HDSC CDC /dev/ttyACM*) │
└──────────────────────────────────────────────┘
```

- 控制循环跑在独立 Python 线程；FastAPI handler 持锁微秒级调用 Controller 命令。
- 状态推送：控制线程 → `asyncio.Queue` → WS 广播。任何客户端 buffer 满直接丢帧。
- USB 断开 → `SerialException` → 进程退出 → `restart: unless-stopped` 拉起。
- `docker stop` 触发 SIGTERM handler，先跑 `safe_shutdown`（缓慢回零 + 失能）再退。

---

## 配置（环境变量）

全部可在 compose 文件的 `environment:` 设置。

| 变量 | 默认 | 说明 |
|------|------|------|
| `MASTER_PORT` | 自动检测 | 强制指定主臂端口（VID/PID 检测多候选时有用） |
| `SLAVE_PORT` | 自动检测 | 强制指定从臂端口 |
| `REBOT_BAUDRATE` | `921600` | 从臂 DM_CAN 波特率 |
| `REBOT_UPDATE_HZ` | `30` | 控制循环频率 |
| `REBOT_RETURN_TIME` | `2.0` | "执行一次"后慢回主臂的时长（秒） |
| `REBOT_TRANSITION_TIME` | `0.6` | 播放前从当前姿态过渡到动作首帧的时长（秒） |
| `REBOT_LOOP_BLEND_TIME` | `0.30` | Loop 模式末尾→开头的平滑过渡（秒） |
| `REBOT_END_HOLD_TIME` | `0.15` | 录制末尾保持帧（秒） |
| `REBOT_GRIPPER` | `1` | 是否带夹爪 |
| `REBOT_RECORDINGS_DIR` | `recordings/` | 动作库根目录 |
| `REBOT_WS_PUSH_HZ` | `10` | WebSocket 推送频率 |
| `REBOT_MOCK` | `0` | `1` = 合成关节数据、跳过串口 I/O，仅用于 UI 联调 / macOS 本地开发 |

---

## 数据 & 持久化

```
recordings/
└── actions/
    └── <id>.json   # 一个动作一个文件（id 是 UUID）
```

每个 JSON：

```json
{
  "id": "01J9...",
  "name": "wave_hello",
  "created_at": "2026-05-07T03:14:00Z",
  "default_play_mode": "once",
  "duration_s": 4.832,
  "frames": [{"t": 0.0, "joint_states": {"joint1": 0.0, "...": 0.0}}, "..."]
}
```

直接 cp 到别处就是备份。

### 老数据迁移（5 槽 → 动作库）

如果之前用过老 demo，根目录有 `slot_<N>.json`。**首次启动**容器时如果 `actions/` 是空的会自动导入，命名 `slot_<N> (imported)`，**不删除**老文件。已经迁移过就跳过（幂等）。

---

## 开发模式

```bash
# 后端（有真机 / Linux 上跑）
uv sync
uv run uvicorn backend.app:app --reload --port 8000

# 后端（无硬件 / macOS 联调 UI）
REBOT_MOCK=1 uv run uvicorn backend.app:app --reload --port 8000

# 前端（Vite dev，:5173 → 代理 /api 和 /ws 到 :8000）
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。修改 `frontend/src/*.tsx` 热重载。

**Mock 模式**：合成 7 路关节的慢正弦运动，slave 端 no-op。完整状态机（follow/record/transition/playback/return_to_follow）行为正常，时长/动作库 IO 都真跑，唯一区别是关节数据和电机控制都是假的。专门给 UI 联调用，**不要用于真机回归**。

---

## 故障排查

**容器启动后立刻退出 / 反复重启**

```bash
docker compose -f deploy/docker-compose.yml logs --tail 50
```

常见原因：
- `Master arm port not found` → 主臂未连接或 VID/PID 不匹配。检查 `lsusb`，必要时 `MASTER_PORT=/dev/ttyUSB1` 强制指定。
- `Slave arm port not found` → 从臂未连接（HDSC CDC）。
- `Permission denied: '/dev/ttyXXX'` → `device_cgroup_rules` 的 char major 不对，按上面"检查硬件"那步重新看一遍。

**Web UI 显示"离线" / 一直转圈**
- 后端进程死了/没起。`docker ps` 看容器状态。
- 防火墙挡了 8000。

**"执行一次"末尾没有平滑回主臂**
- 主臂在 `return_to_follow` 期间读失败 → 进程退出重启。看日志确认。
- 如果 `fashionstar_uart_sdk` 在 playback 期间长时间不读会超时，把 `REBOT_RETURN_TIME` 调低试试，或者改代码在 playback 期间也读但丢弃数据。

---

## License

MIT。`backend/u2can/` 来自 [cmjang/DM_CAN](https://github.com/cmjang/DM_CAN)，MIT。
