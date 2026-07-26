# Waydroid Pen Bridge

[English](README.md) | 简体中文

在**不从合成器热拔笔设备**的前提下，把小米平板 6S Pro（`sheng`）触控笔在
**Linux 桌面**与 **Waydroid** 之间路由。

```text
THP 驱动（M80p / P81c [ / Pro 手势]）
        │
        ▼
 waydroid-pen-relay   ← 双笔型常驻代理 + 可选手势代理
        │
   ┌────┴────┐
 桌面      Android（经 LXC 笔节点）
```

物理驱动节点会被 libinput ignore。relay 为每种笔型保持**一个常驻代理**，只把正在
出帧的型号设为 active，并在有 Pro 手势源时创建手势代理。触摸屏仍走 Wayland。

## 先分清两层概念

| 层级 | 谁设置 | 取值 | 含义 |
|------|--------|------|------|
| **策略 Policy**（托盘 / 快速设置） | 你 | `auto` · `waydroid` · `desktop` | 长期偏好 |
| **运行模式 Runtime**（relay） | session + 策略 | `desktop` · `direct` | **笔坐标**当前去哪 |

```text
策略（自动 / Waydroid / 桌面）
        │
        ▼
Session（焦点、Overview、粘性、抬笔再切）
        │
        ▼
运行模式：desktop 或 direct
```

## 策略（托盘）

GNOME 快速设置与 KDE 系统托盘提供同一套三策略（文案随语言：Auto/Waydroid/Desktop
或 自动/Waydroid/桌面）。

| 策略 | 笔坐标 | 按键 / Pro 手势 |
|------|--------|-----------------|
| **自动** | Waydroid 为有效焦点时 `direct`，否则 `desktop` | 与下表焦点规则一致 |
| **Waydroid** | **始终** `direct`（坐标进 Android） | 侧键/手势侧通道仍常要求 Waydroid 聚焦 |
| **桌面** | **始终** `desktop`（坐标进 Linux 代理） | Waydroid 聚焦时：普通笔键与 Pro 手势可走 **Android 侧通道**，坐标仍留在桌面 |

**自动策略补充**

- Overview 打开时强制走桌面路径。  
- 焦点有防抖与短时 **粘性**，减少误切。  
- 模式切换尽量 **抬笔安全**（tip-safe）：必要时等抬笔再落地。

**策略不是什么**

- 托盘里不会出现 `direct` 这个词（那是 runtime）。  
- 不负责 Notein/Starnote 等应用动作（应在 Android 兼容模块里）。

## 运行模式（relay）

| 模式 | 笔坐标 | 普通笔按键（M80p） | Pro 手势（P81c） |
|------|--------|-------------------|------------------|
| **desktop** | 宿主桌面代理 | 桌面代理；Waydroid 聚焦时可改走 Android `event5` 侧通道 | 桌面手势代理，或按焦点走 Android 手势路径 |
| **direct** | Android `event4` → 当前 active 型号代理 | 聚焦时在笔节点（`event4`）上；**不**再双写到 `event5` | 有 Pro 源时在 `event5`；聚焦时 Android 映射为 194–197 |

共同规则：

- 切模式时双型号代理保持存活（不销毁重建 thrash）。  
- `event4` **仅**在 direct 存在，并指向 **当前 active** 型号。  
- `event5` 仅在侧通道需要时建立。  
- **同一按键帧只进一个目标**，从不双发。  
- 失焦或进 Overview 会先释放 Android 侧按下的笔键。  
- 落在 Waydroid 内容矩形外的笔采样不会进 Android（几何由 GNOME/KWin 上报）。

### 压感与轴

| 型号 | 压感 | 说明 |
|------|------|------|
| M80p | `0..8191` | `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | 可选 brake；Pro 手势是**独立**设备 |

Y 按当前 source 真实范围映射到稳定平板范围，**不改变**压感契约。

### Android 按键传输（不是应用逻辑）

keylayout 只做传输换码：

| 来源 | 扫描码 | Android 键码（常见） |
|------|--------|----------------------|
| 普通笔 / M80p–P81c 笔节点 | 331 / 332 | 194 / 195 |
| Pro 手势设备 | 262–265（`BTN_6`…`BTN_9`） | 194–197 |

P81c 笔迹本身不会“造出” 194/195。应用动作由
`xiaomi-penengine-compat` 一类模块处理，本仓库不包含应用专用逻辑。

## 运行要求

- GNOME Shell 50 **或** KDE Plasma 6 / KWin 6  
- Waydroid 1.6.x  
- Python 3  
- `sudo`、`systemd`、`udevadm`、`visudo`、LXC  
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp)：M80p/P81c
  `2717:3654`，可选 Pro 手势 `0022:5081`

## 安装

### GitHub Release（RPM / DEB）

打 `v*` 标签后 Actions 构建并挂到
[Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases)。

```bash
# Fedora 等
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm

# Debian / Ubuntu
sudo apt install ./waydroid-pen-bridge_*.deb
```

图形登录后若没有托盘/扩展：

```bash
waydroid-pen-bridge-user-setup
```

### 源码安装

```bash
./install.sh
```

两种方式都需要 Waydroid LXC 配置，以及正常的 **xiaomi-sheng-thp**。
本项目**不**替换/卸载 THP，只 ignore 物理节点并经代理转发。

**首次安装后建议重启一次**，让 udev 在登录前隐藏物理笔，并尽早拉起稳定代理。

`install.sh` 会尽量配置用户 UI。若仍没有面板：

```bash
./user-setup.sh
# 或：waydroid-pen-bridge-user-setup
```

- **GNOME：** 按需启用扩展 `Waydroid Pen Mode`  
- **KDE：** 系统托盘 → 条目 → Waydroid Pen Mode → **显示**

### 查看状态

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

底层运行时接口（日常请用托盘策略；一般由 session 自动调用）：

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

安装程序会打开 Android 内置防误触开关，在 Waydroid 容器下次启动后生效。

## 卸载

```bash
./uninstall.sh
```

若当初用 **rpm/dnf** 或 **deb/apt** 安装，`uninstall.sh` 会检测并用包管理器卸包，
再清桌面 UI 并打印自检清单；纯 `install.sh` 安装则走文件清理路径。

只卸 **bridge**：

- 停 relay / link-sync  
- udev、helper、LXC 笔挂载、Android overlay KL/KCM  
- GNOME 扩展与 KDE 托盘/KWin 脚本  
- **保留** [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)

会重启 THP，以重建不带 `LIBINPUT_IGNORE_DEVICE` 的物理笔。仍建议再重启一次会话。

## 架构（简）

| 组件 | 作用 |
|------|------|
| `waydroid-pen-relay` | root 数据面：读 THP → uinput 代理；控制套接字 |
| `waydroid-pen-mode` | root 控制：desktop/direct、focus、map、LXC event4/5 |
| `waydroid-pen-session` | 用户会话：策略 + 焦点/Overview → 调 mode |
| GNOME 扩展 / KDE 托盘 + KWin 脚本 | UI + 窗口几何/焦点 |

## 许可证

见 [LICENSE](LICENSE)。
