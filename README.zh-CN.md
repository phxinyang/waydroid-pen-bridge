<div align="center">
  <h1>Waydroid Pen Bridge</h1>
  <p><b>一个托盘开关,笔在 Linux 桌面和 Waydroid 里都顺手。</b></p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

[English](README.md) | 简体中文

## 功能

- Linux 与 Waydroid 之间自动路由,跟随窗口焦点
- 稳定的 uinput 代理,每次切换都不重建 —— 桌面始终看到同一组设备
- 两种笔型号实时处理:M80p(压感 `0–8191`)和 P81c(`0–16383`,带 brake),外加可选的 Pro 手势
- 笔尖、压感、倾斜和侧键在两边都保留
- GNOME 50 与 KDE Plasma 6 的原生托盘 UI
- 提供 RPM、DEB 和源码安装

## 运行要求

- 小米平板 6S Pro(`sheng`),装有 [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) 提供 M80p / P81c 笔(`2717:3654`),Pro 手势可选(`0022:5081`)
- GNOME Shell 50 **或** KDE Plasma 6 / KWin 6
- Waydroid 1.6.x,且 LXC 容器已配置好
- Python 3、`systemd`,以及常用的 root 工具(`sudo`、`udevadm`、`visudo`、LXC)

## 安装

安装包从 [Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases) 下载:

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

无论哪种方式,都需要一个正常的 `xiaomi-sheng-thp` 单元和 Waydroid 的 LXC 配置
—— 本项目只是路由 THP 的笔,并不替换它。

> [!NOTE]
> 首次安装后重启一次,让 udev 在登录前隐藏物理笔,relay 也能早一步把代理拉起来。

登录后如果没有托盘开关:

```bash
waydroid-pen-bridge-user-setup   # 源码检出可用 ./user-setup.sh
```

- **GNOME:** 启用 *Waydroid Pen Mode* 扩展。
- **KDE:** 系统托盘 → 条目 → *Waydroid Pen Mode* → **显示**。

## 使用

托盘开关(GNOME 快速设置或 KDE 系统托盘)提供三种策略,文案随语言(自动 /
Waydroid / 桌面)。

| 策略 | 笔去哪 | 说明 |
|------|--------|------|
| **自动**(默认) | Waydroid 窗口聚焦时进 Waydroid,否则留桌面 | 绝大多数时候用这个 |
| **Waydroid** | 始终进 Android | 整段记笔记时 |
| **桌面** | 始终留在 Linux 桌面 | Waydroid 应用聚焦时,侧键和 Pro 手势仍可通过侧通道送达 |

平时放在**自动**就不用管了。想看 relay 在做什么:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

`desktop`、`direct`、`focus`、`map`、`unmap` 这些子命令也在,但都由 session 守护
进程替你调用。

## 工作原理

有两个词容易混:

- **策略(Policy)** 是你在托盘里选的 —— `auto`、`waydroid` 或 `desktop`,一个长期偏好。
- **运行模式(Runtime)** 是 relay *此刻* 把笔坐标往哪送 —— `desktop` 或 `direct`,你从不直接设置它。

它们单向串联。策略喂给 session 守护进程;session 盯着窗口焦点和 GNOME/KDE 的
Overview,加一点防抖和粘性,据此把 relay 落到 `desktop` 或 `direct` —— 这才决定
笔进 Linux 还是 Android。

底层是这样:

- `xiaomi-sheng-thp` 暴露原始的 M80p 和 P81c 笔节点(有 Pro 手势时也一并暴露)。udev 把它们对 libinput 隐藏,桌面上没有东西会直接去读。
- `waydroid-pen-relay` 以 root 运行,读正在出帧的那支笔,并持有一组稳定的 uinput 代理:每种型号一支桌面代理、一支隐藏的 Android 代理,再加上侧键和 Pro 手势的侧通道。两种型号全程存活,只写正在落笔的那一支,切换型号从不销毁代理。
- `desktop` 模式下 relay 写桌面代理 —— 当源帧本身就符合代理的轴布局时,原样转发,让笔的热路径保持轻。`direct` 模式下它把帧映射进聚焦 Waydroid 窗口的内容区,经 LXC 喂给隐藏的 Android 代理,并丢掉落在内容区之外的采样。

几条它坚持的规则:

- 每个事件只有一个去处。一帧按键要么进桌面代理,要么进笔自己的 Android 节点,要么进 Android 侧通道,绝不同时进两个。
- 切换抬笔安全:落笔中途,待切换会等你把笔抬起来。
- 失去焦点或打开 Overview 时,先释放按住的 Android 侧键,免得卡住。

## 细节

**运行模式**

| 模式 | 笔坐标 | 侧键(M80p) | Pro 手势(P81c) |
|------|--------|-------------|------------------|
| **desktop** | 桌面代理 | 桌面代理;Waydroid 聚焦时走 Android 侧通道(`event5`) | 桌面手势代理;聚焦时走 Android 手势路径 |
| **direct** | Android `event4`(当前型号) | 走笔自己的 Android 节点 | 有 Pro 源时走 `event5` |

**压感与轴**

| 型号 | 压感 | 其它 |
|------|------|------|
| M80p | `0–8191` | `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0–16383` | brake 轴;Pro 手势是独立设备 |

两支代理暴露同一套平板坐标空间(X `0–30479`,Y `0–20319`)。relay 把每个源的实时
Y 范围映射上去,并把压感夹到该型号自己的范围;它不改写压感协议。

**Android 按键映射**

Android keylayout overlay 把驱动的 Linux 键码映射到 Android 稳定的
`BUTTON_7`–`BUTTON_10` 传输层。把这层传输变成应用动作(比如 Notein / Starnote
的键码 194–197)是另一个兼容层的事,不归本项目管。

| 来源 | Linux 键码 | Android 传输 |
|------|-----------|--------------|
| 笔侧键(M80p / P81c) | 331 / 332 | `BUTTON_7` / `BUTTON_8` |
| Pro 手势 | 262–265 | `BUTTON_7`–`BUTTON_10` |

## 架构

| 组件 | 身份 | 作用 |
|------|------|------|
| `waydroid-pen-relay` | root | 读 THP 笔节点,持有 uinput 代理,暴露控制套接字 |
| `waydroid-pen-mode` | root | 应用 desktop/direct、焦点、几何;管理 LXC 的 `event4` / `event5` 链接 |
| `waydroid-pen-session` | 用户 | 把策略 + 焦点 / Overview 转成 mode 调用 |
| GNOME 扩展 · KDE 托盘 + KWin 脚本 | 用户会话 | 托盘开关,以及上报窗口几何与焦点 |

## 卸载

```bash
./uninstall.sh
```

它会判断你是用 rpm/dnf 还是 deb/apt 装的,并用对应的包管理器卸掉,再清理桌面
UI;纯源码安装则走文件级清理。两种方式都会重启 THP 让物理笔回来,并且不动
[xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)。之后重启一次,让
每个会话都干净地重新发现设备。

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
