# Python 依赖包安装指南

本文档记录在 Windows 系统上安装 Piper-Mate 项目所需 Python 依赖包的完整步骤。

## 所需依赖包

- `pyserial` - 串口通信库
- `fashionstar-uart-sdk` - 时尚之星 UART SDK
- `scipy` - 科学计算库
- `numpy` - 数值计算库

## 安装步骤

### 步骤 1：检查 Python 环境

确认 Python 已正确安装：

```bash
python --version
```

### 步骤 2：检查 pip 配置（可选）

如果遇到安装问题，可以查看 pip 配置：

```bash
pip config list
```

> **注意**：如果配置中同时存在 `global.target` 和 `install.user='yes'`，会导致安装冲突。

### 步骤 3：执行安装命令

使用 `--no-user` 参数绕过配置冲突：

```bash
pip install pyserial fashionstar-uart-sdk scipy numpy --no-user
```

### 步骤 4：验证安装

安装完成后，验证包是否成功安装：

```bash
pip list | findstr "pyserial fashionstar scipy numpy"
```

预期输出示例：

```
fashionstar-uart-sdk    1.3.8
numpy                   2.4.3
pyserial                3.5
scipy                   1.17.1
```

## 常见问题

### 问题 1：`ERROR: Can not combine '--user' and '--target'`

**原因**：pip 配置文件中同时设置了 `--user` 和 `--target` 参数。

**解决方案**：使用 `--no-user` 参数跳过用户配置：

```bash
pip install <package-name> --no-user
```

### 问题 2：pip 版本过旧

如果看到 pip 更新提示，可以执行以下命令更新 pip：

```bash
python -m pip install --upgrade pip
```

## 安装版本信息

本次安装的环境信息：

- 操作系统：Windows
- Python 版本：3.11
- 安装的包版本：
  - `pyserial==3.5`
  - `fashionstar-uart-sdk==1.3.8`
  - `scipy==1.17.1`
  - `numpy==2.4.3`

## 参考链接

- [PySerial 文档](https://pyserial.readthedocs.io/)
- [NumPy 文档](https://numpy.org/doc/)
- [SciPy 文档](https://scipy.org/docs/)
