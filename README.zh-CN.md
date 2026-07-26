<div align="center">
  <h1>Waydroid Pen Bridge</h1>
  <p><b>一个托盘开关，笔在 Linux 桌面和 Waydroid 里都顺手。</b></p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

[English](README.md) | 简体中文

## 功能

- Linux 与 Waydroid 之间自动路由，跟随窗口焦点
- 稳定的 uinput 代理，每次切换都不重建，桌面始终看到同一组设备
- 两种笔型号实时处理：M80p（压感 `0..8191`）和 P81c（`0..16383`，带 brake），外加可选的 Pro 手势
- 笔尖、压感、倾斜和侧键在两边都保留
- GNOME 50 与 KDE Plasma 6 的原生托盘 UI
- 提供 RPM、DEB 和源码安装

## 运行要求

- 小米平板 6S Pro（`sheng`），装有 [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) 提供 M80p / P81c 笔（`2717:3654`），Pro 手势可选（`0022:5081`）
- GNOME Shell 50 **或** KDE Plasma 6 / KWin 6
- Waydroid 1.6.x，且 LXC 容器已配置好
- Python 3、`systemd`，以及常用的 root 工具（`sudo`、`udevadm`、`visudo`、LXC）

## 安装

从 [Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases) 下载安装包：

**Fedora 等**

```bash
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm
```

**Debian / Ubuntu**

```bash
sudo apt install ./waydroid-pen-bridge_*.deb
```

**源码安装**

```bash
./install.sh
```

无论哪种方式，都需要一个正常的 `xiaomi-sheng-thp` 单元和 Waydroid 的 LXC 配置：
本项目只是路由 THP 的笔，并不替换它。

> [!NOTE]
> 首次安装后重启一次，让 udev 在登录前隐藏物理笔，relay 也能早一步把代理拉起来。

登录后如果没有托盘开关：

```bash
waydroid-pen-bridge-user-setup   # 源码检出可用 ./user-setup.sh
```

- **GNOME：** 启用 *Waydroid Pen Mode* 扩展。
- **KDE：** 系统托盘 → 条目 → *Waydroid Pen Mode* → **显示**。

## 使用

托盘开关（GNOME 快速设置或 KDE 系统托盘）提供三种策略，文案随语言（自动 /
Waydroid / 桌面）。

| 策略 | 笔去哪 | 说明 |
|------|--------|------|
| **自动**（默认） | Waydroid 窗口聚焦时进 Waydroid，否则留桌面 | 绝大多数时候用这个 |
| **Waydroid** | 始终进 Android | 整段记笔记时 |
| **桌面** | 始终留在 Linux 桌面 | Waydroid 应用聚焦时，侧键和 Pro 手势仍可通过侧通道送达 |

平时放在**自动**就不用管了。想看 relay 在做什么：

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

## 工作原理

`xiaomi-sheng-thp` 暴露原始的 M80p 和 P81c 笔节点，有 Pro 手势时也一并暴露。
udev 把这些节点对 libinput 隐藏，桌面读不到它们，只能看到 relay 造出来的代理。

`waydroid-pen-relay` 以 root 运行，读正在出帧的那支笔。每种型号各留两支常驻代
理，一支给桌面，一支藏起来给 Android，另有侧键和 Pro 手势的侧通道。代理全程存
活，切换型号或模式都不销毁，变的只是往哪支里写。

写到哪一支，由两层决定：

- **策略（Policy）**：你在托盘里选的 `auto` / `waydroid` / `desktop`，一个长期偏好。
- **运行模式（Runtime）**：relay 此刻的 `desktop` 或 `direct`，由 session 根据策略、窗口焦点和 Overview 算出来，带防抖和粘性，你从不直接设置。

两种模式的走向：

| 模式 | 笔坐标 | 侧键（M80p） | Pro 手势（P81c） |
|------|--------|-------------|------------------|
| **desktop** | 桌面代理 | 桌面代理；Waydroid 聚焦时走 Android 侧通道（`event5`） | 桌面手势代理；聚焦时走 Android 手势路径 |
| **direct** | Android `event4`（当前型号） | 走笔自己的 Android 节点 | 有 Pro 源时走 `event5` |

`direct` 的笔迹经 LXC 进容器，映射到聚焦 Waydroid 窗口的内容区，区外采样直接
丢弃；`desktop` 的源帧符合代理轴布局时原样转发，笔的热路径保持轻。

三条规则贯穿始终：同一个事件只发给一个目的地；模式切换等抬笔，不打断笔画；失
焦或进 Overview 时先释放按住的 Android 侧键，不留卡键。

**压感与轴**

| 型号 | 压感 | 其它 |
|------|------|------|
| M80p | `0..8191` | `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | brake 轴；Pro 手势是独立设备 |

两支代理暴露同一套平板坐标空间（X `0..30479`，Y `0..20319`）。relay 把每个源的实时
Y 范围映射上去，并把压感夹到该型号自己的范围；它不改写压感协议。

**Android 按键映射**

Android keylayout overlay 把驱动的 Linux 键码映射到 Android 稳定的
`BUTTON_7..BUTTON_10` 传输层。把这层传输变成应用动作（比如 Notein / Starnote
的键码 194-197）是另一个兼容层的事，不归本项目管。

| 来源 | Linux 键码 | Android 传输 |
|------|-----------|--------------|
| 笔侧键（M80p / P81c） | 331 / 332 | `BUTTON_7` / `BUTTON_8` |
| Pro 手势 | 262-265 | `BUTTON_7..BUTTON_10` |

## 架构

| 组件 | 身份 | 作用 |
|------|------|------|
| `waydroid-pen-relay` | root | 读 THP 笔节点，持有 uinput 代理，暴露控制套接字 |
| `waydroid-pen-mode` | root | 应用 desktop/direct、焦点、几何；管理 LXC 的 `event4` / `event5` 链接 |
| `waydroid-pen-session` | 用户 | 把策略 + 焦点 / Overview 转成 mode 调用 |
| GNOME 扩展 · KDE 托盘 + KWin 脚本 | 用户会话 | 托盘开关，以及上报窗口几何与焦点 |

## 卸载

```bash
./uninstall.sh
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
