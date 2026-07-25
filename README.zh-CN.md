# Waydroid Pen Bridge

[English](README.md) | 简体中文

在不从合成器热移除数位笔设备的情况下，在桌面和 Waydroid 之间切换小米平板 6S Pro（`sheng`）的触控笔输入。

驱动创建的 `M80p` 和 `P81c` 触控笔设备会被 libinput 忽略。系统服务会为两种笔型各保持一个常驻代理，只把实际产生帧的 source 设为 active，并在 Pro 手势源存在时创建可选的手势代理。

## 模式策略

GNOME 快速设置菜单和 KDE Plasma 系统托盘提供相同的三种策略：

- **自动：** 跟随当前聚焦的窗口。
- **Waydroid：** 始终将物理 evdev 触控笔坐标发送到 Android；普通笔和 Pro 的按键仍要求 Waydroid 窗口处于聚焦状态。
- **桌面：** 始终将物理触控笔转发到稳定的桌面代理设备。Waydroid 窗口获得焦点时，普通笔按钮和 Focus Pen Pro 手势通过独立的 Android 侧通道发送，不改变笔坐标的桌面路径。

触摸屏输入继续通过 Wayland 传递。bridge 在 Linux 侧原样保留普通笔的 `BTN_STYLUS`/`BTN_STYLUS2` 和 Pro 的 `BTN_6` 至 `BTN_9`，不在宿主侧指定应用动作。M80p 代理保持原生压力 `0..8191`，P81c 代理保持原生压力 `0..16383`；只按当前 source 的真实 Y 范围映射到稳定代理，切换笔型时不销毁或重建桌面数位板设备。

安装程序还会在 Android 中启用内置的防误触开关。该设置会在 Waydroid 容器下次启动时生效。

## 运行模式

- **桌面模式：** 普通 Focus Pen（非 Pro）保留两颗标准笔按钮，Focus Pen Pro 在稳定桌面手势代理上原样保留 `BTN_6`/`BTN_7`/`BTN_8`/`BTN_9`。Android 的 `event4` 不会建立；Waydroid 窗口获得焦点时，当前笔的原始按键帧改走 Android `event5`，不再写入桌面按键目标。
- **普通 Focus Pen（非 Pro）的直通模式：** Android 的 `event4` 指向触控笔代理设备，并在 Waydroid 窗口聚焦时保留 `BTN_STYLUS`/`BTN_STYLUS2`。直通模式不会把普通笔按钮重复连接到 `event5`。
- **Focus Pen Pro 的直通模式：** `P81c` 触控笔帧通过 `event4` 传递。独立的 Pro 手势输入源在 `event5` 上保留扫描码 `262`、`263`、`264` 和 `265`（即 `BTN_6` 至 `BTN_9`）。宿主 Waydroid 窗口获得焦点时，Android 将它们映射为键码 `194` 至 `197`。

切换模式时，bridge 创建的两个笔型代理保持不变。Android `event4` 只在直通模式存在，并指向当前 active 笔型；`event5` 只在当前焦点路径需要时建立。Pro 手势代理只在物理 Pro 手势源存在时创建。窗口失焦或进入 Overview 时，会先释放 Android 中所有处于按下状态的笔按钮。

每个按键动作只进入一个目标：桌面焦点使用对应的桌面代理，普通笔在聚焦的直通模式使用 Android `event4`，桌面旁路和 Pro 手势使用 Android `event5`。relay 不会把同一按键帧同时写入两条路径。

GNOME 扩展和 KWin 脚本会跟随 Waydroid 窗口的移动、缩放、全屏状态、显示器缩放比例和显示器位置。落在 Waydroid 内容区域之外的触控笔事件不会发送到 Android。使用自动策略时，进入 GNOME Overview 或 KDE Overview 会临时切回桌面模式。

Android keylayout 只负责传输转换：普通笔或 M80p/P81c 笔节点的扫描码 `331/332` 变成 `BUTTON_7/8`，由 Android 暴露为 `194/195`；Pro 手势源的 `262–265` 变成 `BUTTON_7–10`，由 Android 暴露为 `194–197`。P81c 笔节点本身不会直接产生 `194/195`。Notein、Starnote 等应用的具体动作由 `xiaomi-penengine-compat` 一类 Android 兼容模块处理，bridge 不包含应用专用逻辑。

## 运行要求

- GNOME Shell 50 或 KDE Plasma 6 / KWin 6
- Waydroid 1.6.x
- Python 3
- `sudo`、`systemd`、`udevadm`、`visudo` 和 LXC
- [`xiaomi-sheng-thp.service`](https://github.com/ianchb/xiaomi-sheng-thp)，需提供 `M80p`/`P81c` 的 `2717:3654` 触控笔节点，以及可选的 `0022:5081` `Xiaomi Focus Pen Pro Gestures` 节点

## 安装

```bash
./install.sh
```

`install.sh` 需要已有 Waydroid LXC 配置，以及已安装的
[`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp)。
它不会替换或卸载 THP 驱动，只是让 libinput 忽略驱动节点，并通过稳定代理转发。

安装后重启一次。重启可以让 udev 在桌面登录前隐藏物理触控笔，并让 relay 创建稳定代理。

桌面 UI（GNOME 扩展 / KDE 托盘）由 `user-setup.sh` 配置，`install.sh` 也会调用它。
若登录后看不到模式切换面板：

```bash
./user-setup.sh
```

GNOME 可再启用 `Waydroid Pen Mode`；KDE 可在系统托盘 → 条目里把 Waydroid Pen Mode 设为显示。

查看当前运行模式：

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

手动选择运行模式：

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
```

`focus 1` 会先检查 `event5`，再启用当前笔的 Android 按键通道；`focus 0` 会立即释放 Android 中全部笔按钮。GNOME 和 KDE 的窗口焦点监听器会自动调用这两个命令。

手动设置归一化后的 Waydroid 内容区域：

```bash
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

`unmap` 会恢复覆盖整个屏幕的恒等映射。

## 卸载

```bash
./uninstall.sh
```

卸载只移除 bridge 本身：

- 停止并禁用 `waydroid-pen-relay` / link-sync
- 删除 udev 规则、helper、LXC 笔挂载、Android overlay 的 KL/KCM
- 删除 GNOME 扩展与 KDE 托盘/KWin 模式切换面板
- **保留** [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp)

卸载会重启 THP，以重建不带 `LIBINPUT_IGNORE_DEVICE` 的物理笔节点。仍建议重启一次。卸载后桌面笔应再次直接来自 THP。
