# LabCapsule 0.10.0 Alpha（统一桌宠 / Live2D）

## 本次发布文件

- `LabCapsule-Studio-0.10.0.exe` — Windows 10/11 单文件桌面工作室，82,374,001 字节，支持本地/网络图片、GIF 和 Live2D Cubism 3+ 角色包。

本版没有改动设备协议、分区和 Android 客户端。继续使用 V0.7 配套文件：

- `LabCapsule-0.7.0.apk` — Android 8.0+ 简体中文控制器。
- `LabCapsule-0.7.0-ota.bin` — ESP32-S3 V0.7 固件 OTA 镜像。

## SHA-256

```text
A1363866FEB5AE25C7F89E982C4826B88CCFFAC32603045873DA6A88178F57F9  LabCapsule-Studio-0.10.0.exe
```

当前 EXE 没有 Authenticode 签名。请从本仓库 GitHub Release 下载并核对 SHA-256；Windows SmartScreen 可能显示未知发布者。

## 更新与安装

1. 下载并运行 `LabCapsule-Studio-0.10.0.exe`，无需安装 Python。
2. 使用数据线连接 CH343/COM8；程序不会更改电脑 Wi-Fi，也不会连接设备的无网络恢复热点。
3. 设备继续运行 `0.7.0-alpha` 固件即可；不需要重新烧录，也不会自动改变已有壁纸、动画和离线实验。
4. 进入“AI 桌宠”，可从网络形象库选择图片/GIF，也可选择包含一个或多个 `*.model3.json` 的 Live2D 文件夹；程序会递归识别角色。
5. 首次启用 Live2D 时阅读许可说明并由素材权利人本人确认；许可版本匹配时，重启可恢复当前角色和舞台。
6. 如需显示到设备，先将当前静态/GIF 形象送到屏幕工作室检查 240×320 预览，再由用户显式点击上传。Live2D 目前只在电脑端渲染，不复制到 ESP32。

## 重点变化

- 统一图片、GIF 与 Live2D 为可扫描的桌宠条目；目录中存在多个 `model3.json` 时一次列出全部角色。
- Live2D 读取 Cubism 3+ `model3.json` 的运行时依赖图、动作和表情，网页播放器仅绑定 `127.0.0.1`，拒绝目录穿越。
- Pixi、Live2D 显示插件和无 eval 兼容包固定版本，播放器保持严格 CSP，不开放 `unsafe-eval`。
- 桌宠身份、AI 系统提示、主舞台和透明悬浮层共享同一角色；透明层支持拖动、点击触发动作和网页内关闭。
- 仓库内新增 `labcapsule-pet-creator` Skill，可直接扫描素材文件夹并生成统一角色包；只复制实际依赖文件，不包含测试用 Hiyori 素材。
- 延续 V0.9 的 HTTPS 网络形象限制、失败回滚、单份缓存和 GIF 本地逐帧播放；Live2D 只消耗电脑端资源。

## 验证摘要

- 30/30 Python 自动化测试通过，仓库内 Skill 结构验证通过。
- npm 生产依赖审计为 0 漏洞，Live2D Web 生产构建通过。
- Hiyori Free/Pro 从同一父目录直接识别为 8/10 个动作，并分别完成 WebGL 动态渲染测试。
- 最终 EXE 完成角色选择、点击动作、透明悬浮层、重启恢复和关闭子进程测试。
- COM8 真机返回 `PONG,LABCAPSULE,0.7.0-alpha` 和 `STATUS,READY,MPU=OK,MOCK=OFF,SAMPLES=0,RATE=200,DURATION=10`。
- 本轮没有启动实验、上传媒体、烧录固件或修改设备/电脑 Wi-Fi。

完整步骤见：

- `docs/V0.10.0_UNIFIED_PET_PACKAGE_TEST_ZH.md`
- `docs/V0.10.0_TEST_REPORT_ZH.md`
- `skills/labcapsule-pet-creator/SKILL.md`
