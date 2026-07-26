# Waydroid Pen Bridge

[English](README.md) | 简体中文

**一个托盘开关，让笔同时在 Linux 和 Waydroid 里正常工作，不用顾此失彼。**

我在小米平板 6S Pro（`sheng`）上日常跑 Linux + Waydroid 记笔记。
Waydroid 里写字不应牺牲桌面笔体验，切换也不该像在走钢丝。

于是做了一个薄 relay：夹在 [THP
驱动](https://github.com/ianchb/xiaomi-sheng-thp) 和系统中间，
给两侧各配一套稳定代理，快到体感上你很可能感觉不到它在那。

## 快速上手

确保 [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) 已装好
并在跑。然后：

```bash
# 下 Release 里的包（RPM / DEB）
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm   # Fedora 类
sudo apt install ./waydroid-pen-bridge_*.deb           # Debian/Ubuntu

# 或者源码装
./install.sh

# 重启一次，登录后若没看到托盘图标：
waydroid-pen-bridge-user-setup
```

托盘会出现 **自动 / Waydroid / 桌面** 三个选项。日常切到需要的，接着写就行。

卸载：

```bash
./uninstall.sh
```

不论当初是 rpm、deb 还是 `install.sh` 装的，都能卸干净。不会动 THP。

## 它是怎么工作的

THP 驱动提供 M80p、P81c 和可选的 Pro 手势设备。我的 relay 把它们从桌面
隐藏掉，避免两方抢同一个物理节点。然后为每种笔型建**常驻代理**——Linux 一套，
Android 一套——再按托盘选的状态决定走哪边。

有两个概念容易搞混：

| 是什么 | 在哪看到 | 含义 |
|--------|----------|------|
| **策略** | 托盘 / 快速设置 | `auto` / `waydroid` / `desktop`，你长期选的偏好 |
| **运行模式** | relay 内部 | `desktop` / `direct`，笔坐标当前实际去哪 |

策略 → session（焦点、Overview、粘性、抬笔安全）→ 运行模式。托盘选「自动」，
session 根据当下情况决定是 `desktop` 还是 `direct`。

### 三种策略干了什么

**自动**——我推荐日常用。跟随 Waydroid 焦点：Waydroid 为活动窗口时走 direct，
否则留在桌面。Overview 打开时强制桌面。焦点有防抖、有短时粘性，不会一抖就切。
需要时会等抬笔再换模式。

**Waydroid**——笔坐标始终进 Android。但侧键和 Pro 手势侧通道仍常要求
Waydroid 窗口聚焦。

**桌面**——笔坐标始终留在 Linux。不过 Waydroid 聚焦时，普通笔按钮和 Pro
手势可以走一条独立的 Android 侧通道，让你的按键在 Waydroid 应用里生效，
同时笔坐标不动。

### 运行模式：desktop vs direct

| 模式 | 笔坐标 | M80p 按键 | P81p Pro 手势 |
|------|--------|-----------|---------------|
| **desktop** | 桌面代理 | 桌面代理，或 Waydroid 聚焦时走 Android `event5` 侧通道 | 桌面手势代理，聚焦时走 Android 手势路径 |
| **direct** | Android `event4`（当前 active 型号） | 在笔节点上；不会双发到 `event5` | Android `event5`；聚焦时扫测码映射为 194–197 |

### 压感与按键（简短版）

M80p 压感 `0..8191`，带 `BTN_STYLUS`/`BTN_STYLUS2`。P81c 压感 `0..16383`，
可选 brake，Pro 手势是独立设备。Y 从真实 source 范围映射到稳定平板空间，
不碰压感契约。

本 bridge 只负责把按键事件送到位，不指定 Starnote / Notein 这些应用具体
做什么。那是 [`xiaomi-penengine-compat`](https://github.com/phxinyang) 的事。

### 一个按键只进一个门

每个按键帧只落一个目标：桌面焦点 → 桌面代理；普通笔聚焦 direct → `event4`；
桌面 + 聚焦侧通道 → `event5`。不会同一帧双发。

### GNOME 和 KDE 都能用

托盘 / 快速设置是一样的三种策略。KWin 脚本和 GNOME 扩展负责把窗口几何和
焦点变化交给 session，relay 就知道 Waydroid 目前在屏幕哪个位置、是不是
焦点窗口。落在 Waydroid 内容矩形外的笔采样不会进 Android。

## 运行要求

- 一块跑 Fedora 的 sheng（或类似，需 GNOME 50+ / KDE Plasma 6）
- Waydroid 1.6.x
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp)（提供 M80p/P81c，可选 Pro 手势）
- Python 3、`sudo`、`systemd`、LXC

## 翻开看看

四块东西，平时你只跟托盘打交道：

| 组件 | 身份 | 做的事 |
|------|------|--------|
| `waydroid-pen-relay` | root | 读 THP、写 uinput 代理、管理控制 socket |
| `waydroid-pen-mode` | root | desktop/direct 切换、focus、map、LXC `event4`/`event5` |
| `waydroid-pen-session` | user | 策略 + 上下文 → 调 mode helper |
| 托盘 / 扩展 | 桌面 | GNOME Quick Settings 或 KDE 托盘切换 |

出问题的话，先看这个：

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

底层的调试接口（一般不需要手动用）：

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

## 卸载

```bash
./uninstall.sh
```

若当初是 rpm/deb 装的，脚本会用包管理器卸包，再清桌面 UI 并打印自检清单。
`install.sh` 装的会走文件清理。无论哪种，THP 都在。

## 关于延迟

桌面场景，relay 的 host 侧开销大概 **p50 ~0.04 ms**（Rust 版）。
Waydroid 笔记感觉钝，大头在 Android 输入栈和 App 本身，不是这个桥。

对实现好奇的话，可以看 `rust-rewrite` 分支上的 Rust 数据面。

## 许可证

MIT — [LICENSE](LICENSE)
