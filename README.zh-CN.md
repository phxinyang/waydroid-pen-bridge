# Waydroid Pen Mode

[English](README.md) | 简体中文

在不从合成器热移除数位笔设备的情况下，在桌面和 Waydroid 之间切换小米平板 6S Pro（`sheng`）的触控笔输入。

驱动创建的 `M80p` 和 `P81c` 触控笔设备会被 libinput 忽略。系统服务负责选择当前输入源，并为桌面和 Android 创建稳定的触控笔及手势代理设备。

## 模式策略

GNOME 快速设置菜单和 KDE Plasma 系统托盘提供相同的三种策略：

- **自动：** 跟随当前聚焦的窗口。
- **Waydroid：** 始终将物理 evdev 触控笔发送到 Android。
- **桌面：** 始终将物理触控笔转发到稳定的桌面代理设备。

触摸屏输入继续通过 Wayland 传递。Focus Pen Pro 的上下滑手势在桌面和直通模式下使用独立的手势代理设备。

安装程序还会在 Android 中启用内置的防误触开关。该设置会在 Waydroid 容器下次启动时生效。

## 运行模式

- **桌面模式：** 普通 Focus Pen（非 Pro）保留两颗标准笔按钮。Focus Pen Pro 将 `BTN_6`/`BTN_7` 映射为稳定触控笔设备上的 `BTN_STYLUS`/`BTN_STYLUS2`，并将 `BTN_8`/`BTN_9` 映射为 `KEY_PROG3`/`KEY_PROG4`。Android 事件链接不会建立。
- **普通 Focus Pen（非 Pro）的直通模式：** Android 的 `event4` 指向触控笔代理设备，并保留 `BTN_STYLUS`/`BTN_STYLUS2`。`event5` 不会建立。
- **Focus Pen Pro 的直通模式：** `P81c` 触控笔帧通过 `event4` 传递。独立的 Pro 手势输入源将轻捏、双击、上滑和下滑分别映射为扫描码 `148`、`149`、`202` 和 `203`，Android 再通过 `event5` 将它们映射为键码 `194` 至 `197`。

切换模式时，bridge 创建的代理设备保持不变。只有 Focus Pen Pro 的可用状态发生变化时，Android 的 `event5` 链接才会建立或移除。

GNOME 扩展和 KWin 脚本会跟随 Waydroid 窗口的移动、缩放、全屏状态、显示器缩放比例和显示器位置。落在 Waydroid 内容区域之外的触控笔事件不会发送到 Android。使用自动策略时，进入 GNOME Overview 或 KDE Overview 会临时切回桌面模式。

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

安装后重启一次。重启可以让 udev 在 GNOME 启动前隐藏物理触控笔，并让 relay 在登录前创建稳定的代理设备。GNOME 用户随后需要启用 `Waydroid Pen Mode` 扩展。KDE 用户安装后会自动启用 KWin 脚本，并在系统托盘中加入 `Waydroid Pen Mode`。

查看当前运行模式：

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

手动选择运行模式：

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
```

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

卸载后请重启，使代理服务在 GNOME 会话之外退出，并让 libinput 重新识别物理触控笔。
