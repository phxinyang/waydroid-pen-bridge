# Waydroid Pen Bridge

[English](README.md) | 简体中文

Waydroid Pen Bridge 用于在 **Linux 桌面** 与 **Waydroid** 之间无缝切换小米平板
6S Pro（`sheng`）触控笔输入。

它基于 [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)，通过稳定的
uinput 代理，将触控笔输入按当前策略动态路由到：

- Linux 桌面（Wayland）
- Waydroid（Android）

整个过程中，桌面始终看到同一组代理设备，不会因为切换目标而发生设备重建。

## Features

- Linux 与 Waydroid 间自动切换笔输入
- 稳定 uinput 代理，不因切换重建设备
- 支持 M80p、P81c 与可选 Pro 手势设备
- GNOME 50 与 KDE Plasma 6 原生集成
- 支持 RPM、DEB 与源码安装

## 工作原理

`xiaomi-sheng-thp` 提供 M80p、P81c 以及可选的 Pro 手势输入源。

Waydroid Pen Bridge 的 `waydroid-pen-relay` 从这些输入源读取事件，并维护稳定的
uinput 代理设备。根据当前策略和窗口焦点，笔输入会被路由到 Linux 桌面，或通过
LXC 映射进入 Waydroid。

物理输入设备会被 `LIBINPUT_IGNORE_DEVICE` 隐藏，因此桌面只会看到 relay 创建的
代理设备。relay 会为每种笔型号维护一个长期存在的代理设备，仅切换当前 active
型号；如果存在 Pro 手势输入源，还会额外创建对应的手势代理。触摸输入始终直接走
Wayland，不经过 relay。

## 理解策略与运行模式

有两层概念容易混在一起：

| 层级 | 谁设置 | 取值 | 含义 |
|------|--------|------|------|
| **策略 Policy**（托盘 / 快速设置） | 你 | `auto` · `waydroid` · `desktop` | 长期偏好 |
| **运行模式 Runtime**（relay） | session + 策略 | `desktop` · `direct` | **笔坐标**当前去哪 |

整体流程如下：

```text
策略（Policy）
        │
        ▼
session 根据焦点 / Overview / 粘性
        │
        ▼
relay 决定运行模式（desktop 或 direct）
        │
        ▼
笔输入进入 Linux 或 Android
```

### 策略（托盘）

GNOME 快速设置与 KDE 系统托盘提供同一套三策略（文案随语言：Auto / Waydroid /
Desktop，或 自动 / Waydroid / 桌面）。

| 策略 | 笔坐标 | 按键 / Pro 手势 |
|------|--------|-----------------|
| **自动** | Waydroid 为有效焦点时 `direct`，否则 `desktop` | 与下表焦点规则一致 |
| **Waydroid** | **始终** `direct`（坐标进 Android） | 侧键 / 手势侧通道仍常要求 Waydroid 聚焦 |
| **桌面** | **始终** `desktop`（坐标进 Linux 代理） | Waydroid 聚焦时：笔按键与 Pro 手势可走 **Android 侧通道**，坐标仍留在桌面 |

**自动策略补充**

- Overview 打开时强制走桌面路径。
- 焦点有防抖与短时粘性，减少误切。
- 模式切换尽量抬笔安全（tip-safe）：必要时等抬笔再落地。

**策略不会做什么**

- UI 中不会出现 `direct` 这个词；它属于 relay 的内部运行模式。
- 策略不负责 Notein / Starnote 等应用动作（应在 Android 兼容模块里）。

### 运行模式（relay）

| 模式 | 笔坐标 | 笔按键（M80p） | Pro 手势（P81c） |
|------|--------|----------------|------------------|
| **desktop** | 宿主桌面代理 | 桌面代理；Waydroid 聚焦时可改走 Android `event5` 侧通道 | 桌面手势代理，或按焦点走 Android 手势路径 |
| **direct** | Android `event4`（当前 active 型号） | 聚焦时在笔节点（`event4`）上；不双写到 `event5` | 有 Pro 源时在 `event5`；聚焦时 Android 映射为 194–197 |

共同规则：

- 双型号代理始终保持存活，不因模式切换而销毁重建。
- `event4` 仅在 direct 模式存在，并始终对应当前 active 型号。
- `event5` 仅在需要 Android 侧通道时创建。
- 同一按键事件永远只会发送到一个目标。
- 进入 Overview 或失去焦点时，会先释放 Android 侧按下状态。
- Waydroid 内容区域外的采样不会进入 Android（几何由 GNOME / KWin 上报）。

### 压感与轴

| 型号 | 压感 | 说明 |
|------|------|------|
| M80p | `0..8191` | `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | 可选 brake；Pro 手势是独立设备 |

Y 轴会根据当前输入源的实际范围映射到统一的平板坐标范围，不影响压感协议。

### Android 按键映射

这里只负责 Linux → Android 的按键映射，不包含任何应用层行为。

| 来源 | 扫描码 | Android 键码（常见） |
|------|--------|----------------------|
| 笔节点（M80p / P81c） | 331 / 332 | 194 / 195 |
| Pro 手势设备 | 262–265（`BTN_6`…`BTN_9`） | 194–197 |

P81c 笔迹本身不会“造出” 194/195。应用动作由 `xiaomi-penengine-compat` 一类模块
处理，本仓库不包含应用专用逻辑。

## 运行要求

- GNOME Shell 50 **或** KDE Plasma 6 / KWin 6
- Waydroid 1.6.x
- Python 3
- `sudo`、`systemd`、`udevadm`、`visudo`、LXC
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp)：M80p/P81c
  `2717:3654`，可选 Pro 手势 `0022:5081`

## 安装

### 推荐：GitHub Release（RPM / DEB）

打 `v*` 标签后 Actions 构建并挂到
[Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases)。

```bash
# Fedora 等
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm

# Debian / Ubuntu
sudo apt install ./waydroid-pen-bridge_*.deb
```

图形登录后若没有托盘 / 扩展：

```bash
waydroid-pen-bridge-user-setup
```

### 源码安装

如果希望自行开发或调试，可使用源码安装：

```bash
./install.sh
```

两种方式都需要 Waydroid LXC 配置，以及正常的 **xiaomi-sheng-thp**。本项目不
替换 / 卸载 THP，只隐藏物理节点并经代理转发。

> [!NOTE]
> 首次安装后建议重启一次，使 udev 在登录前隐藏物理笔设备，并提前启动稳定代理。

`install.sh` 会尽量配置用户 UI。若仍没有面板：

```bash
./user-setup.sh
# 或：waydroid-pen-bridge-user-setup
```

- **GNOME：** 按需启用扩展 `Waydroid Pen Mode`
- **KDE：** 系统托盘 → 条目 → Waydroid Pen Mode → **显示**

### 常用命令

查看当前状态：

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

以下接口主要供 session 调用，日常通常无需手动执行：

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

日常请优先用**托盘策略**。GNOME / KDE 会从窗口监听自动调用 `focus` / `map`。

安装程序会打开 Android 内置防误触开关，在 Waydroid 容器下次启动后生效。

## 卸载

```bash
./uninstall.sh
```

若当初用 **rpm/dnf** 或 **deb/apt** 安装，`uninstall.sh` 会检测并用包管理器卸包，
再清桌面 UI 并打印自检清单；纯 `install.sh` 安装则走文件清理路径。

卸载 Bridge 后，将移除：

- relay / link-sync 服务
- udev 规则、helper、LXC 笔挂载、Android overlay 的 KL/KCM
- GNOME 扩展与 KDE 托盘 / KWin 脚本

不会卸载 [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)。

会重启 THP，以重建不带 `LIBINPUT_IGNORE_DEVICE` 的物理笔。仍建议再重启一次会话。

## 架构

| 组件 | 作用 |
|------|------|
| `waydroid-pen-relay` | root 数据面：读 THP → uinput 代理；控制套接字 |
| `waydroid-pen-mode` | root 控制：desktop/direct、focus、map、LXC event4/5 |
| `waydroid-pen-session` | 用户会话：策略 + 焦点/Overview → 调 mode |
| GNOME 扩展 / KDE 托盘 + KWin 脚本 | UI + 窗口几何/焦点 |

## 许可证

见 [LICENSE](LICENSE)。
