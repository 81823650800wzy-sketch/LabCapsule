# LabCapsule 1.0.0 Alpha（统一随身实验助手）

## 发布文件

- `LabCapsule-Studio-1.0.0.exe` — Windows 10/11 单文件 Studio，85,841,923 字节。
- `LabCapsule-1.0.0.apk` — Android 8.0+ 简体中文控制器，352,822 字节。
- `LabCapsule-1.0.0-ota.bin` — ESP32-S3 V1.0.0 应用 OTA 镜像，1,398,704 字节。

## SHA-256

```text
6CBEC60592639EF7463B7133DAD47CF4FF5EB661FBE25AAF37D7E4918F990C35  LabCapsule-Studio-1.0.0.exe
4A6E96A8ECCC5569864AACCAB65911D10EF2446F47C9F3C0F21A62271D91F943  LabCapsule-1.0.0.apk
675DA5103E6B53C496F9E6206883D56ED906375E0196C23EB7FB44FF710DF685  LabCapsule-1.0.0-ota.bin
```

EXE 当前没有 Authenticode 签名，APK 为开发签名。请只从本仓库 GitHub Release 下载并核对 SHA-256；商业发行前需替换正式证书。

## 安装顺序

1. 首次使用 V1 或分区表变化时，在 `firmware` 目录执行 `idf.py -p COM8 flash`；不要执行 `erase-flash`。
2. Windows 运行 `LabCapsule-Studio-1.0.0.exe`；Android 安装 `LabCapsule-1.0.0.apk`。
3. 保持手机/电脑在正常有网络连接上，优先用 USB 或 BLE 找到设备；不要长期连接恢复热点。
4. 核对稳定设备 ID。COM8 本次实机为 `lc-000000000000`。
5. Windows 已可从用户目录恢复 Hiyori Free。Android 需把完整 Hiyori 文件夹复制到手机并在 AI 页选择；模型不包含在发布包中。
6. 如需跨端记忆，在双端配置用户自己的私有 GitHub 仓库和最小权限 Token。

## 重点变化

- Windows、Android、实体屏统一 Hiyori 内容 ID `live2d-000000000000`；旧 `local-*` 自动迁移。
- Windows 增加 USB/LAN/BLE 三链路、语音转写、私有记忆、持久实验会话和简化导航。
- Android 增加统一 Hiyori 对话、系统语音、Live2D 文件夹导入、私有记忆和真实 240:320 舞台。
- 设备暴露稳定硬件身份、角色代理、STA 状态、传感器与 `MIC_PORT` 扩展能力。
- GIF/Hiyori 代理一次写入设备本地并持续播放；AI 回答只同步安全动作和底部气泡。
- 新增按需组件/设备上下文 Skill，防止 AI 为每次问题加载整个仓库。
- 修复扩展 I²C 扫描对已启动 MPU 的争用；USB 和 BLE 均返回 MPU6050 0x68。

## 验证摘要

- 54/54 Python 自动化测试通过。
- Android versionCode 100 / versionName 1.0.0，APK v2/v3 签名通过，包内 Live2D 播放器资产完整。
- ESP-IDF 5.5.4 构建通过，3 MiB app 分区剩余 56%；最终 OTA 镜像已写入 COM8 并通过哈希校验。
- COM8 返回 V1 身份、MPU OK、传感器 count 1、Hiyori proxy ON。
- Windows BLE 实机读取同一身份、角色、网络字段和传感器。
- 源码与最终 EXE 均用用户现有 Hiyori Free 完成 24 帧、8 FPS 捕获；EXE 隐藏启动 20 秒保持运行。
- 当前无 ADB 手机，故 Android 真机 Live2D WebView 仍需用户安装后执行指南中的首次导入验收。

完整指南：`docs/V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md`

测试证据：`docs/V1.0.0_TEST_REPORT_ZH.md`

按需上下文 Skill：`skills/labcapsule-context-access/SKILL.md`
