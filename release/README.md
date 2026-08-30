# LabCapsule 0.9.0 Alpha（Network Avatar / Desktop First）

## 本次发布文件

- `LabCapsule-Studio-0.9.0.exe` — Windows 10/11 单文件桌面工作室，74,037,672 字节，内含 FFmpeg 视频解码组件与 PNG/JPG/WebP/GIF 网络形象链路。

本版没有改动设备协议、分区和 Android 客户端。继续使用 V0.7 配套文件：

- `LabCapsule-0.7.0.apk` — Android 8.0+ 简体中文控制器。
- `LabCapsule-0.7.0-ota.bin` — ESP32-S3 V0.7 固件 OTA 镜像。

## SHA-256

```text
641BC783FA2F190B66102E16277384405EB142EB408F5C394FE41F13AC1D413B  LabCapsule-Studio-0.9.0.exe
```

当前 EXE 没有 Authenticode 签名。请从本仓库 GitHub Release 下载并核对 SHA-256；Windows SmartScreen 可能显示未知发布者。

## 更新与安装

1. 下载并运行 `LabCapsule-Studio-0.9.0.exe`，无需安装 Python。
2. 使用数据线连接 CH343/COM8；程序不会更改电脑 Wi-Fi，也不会连接设备的无网络恢复热点。
3. 设备继续运行 `0.7.0-alpha` 固件即可；不需要重新烧录，也不会自动改变已有壁纸、动画和离线实验。
4. 进入“AI 桌宠 → 网络形象库 / URL”，使用 DiceBear CC0 预设或粘贴 HTTPS PNG/JPG/WebP/GIF 直链。
5. 如需显示到设备，先点击“将当前形象送到屏幕工作室”检查 240×320 预览，再由用户显式点击上传。

## 重点变化

- 支持任意 HTTPS PNG/JPG/WebP/GIF 网络形象，主舞台、桌面悬浮宠物与屏幕工作室共享当前形象。
- 内置 DiceBear Pixel Art、Lorelei、Thumbs、Shapes 四个 CC0 预设和稳定种子；软件内提供官方目录、许可证、VRoid、VRoid Hub、Live2D 与本项目说明入口。
- 公网强制 HTTPS；限制 12 MiB、2048²、4,194,304 像素、120 帧和总解码量；拒绝带账户凭据、伪装响应、未知格式和损坏缓存。
- 当前形象使用 SHA-256 与单份原子缓存；新形象失败时保留旧形象，重启软件自动恢复。
- GIF 按文件逐帧时序在电脑端播放，最快 33 ms/帧；不依赖手机后台传帧，不增加 ESP32-S3 动画负载。
- 根据 Windows 150% DPI 真机巡检缩短角色舞台、合并悬浮宠物按钮并扩展形象库高度，所有主要操作和资源链接完整可见。

## 验证摘要

- 13/13 自动化测试通过：网络安全策略、PNG/GIF、重定向、上限、哈希、失败回滚、缓存清理、Tk 主舞台/悬浮层/形象库/屏幕交接、实验数据校验、图表峰值、AI Endpoint 与秘密脱敏。
- DiceBear 10.x 真实公网下载、解码和打包 EXE 内再次下载均通过。
- 最终 EXE 的缓存恢复、240×320 预览和 Windows 150% DPI 界面通过。
- COM8 真机返回 `PONG,LABCAPSULE,0.7.0-alpha` 和 `STATUS,READY,MPU=OK,MOCK=OFF,SAMPLES=0,RATE=200,DURATION=10`。
- 本轮没有启动实验、上传媒体、烧录固件或修改设备/电脑 Wi-Fi。

完整说明和可直接复制的网址见 `docs/V0.9.0_NETWORK_AVATAR_GUIDE_ZH.md`。
