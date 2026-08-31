# LabCapsule 0.11.0 Alpha（实体桌宠 / AI / Claude）

## 本次发布文件

- `LabCapsule-Studio-0.11.0.exe` — Windows 10/11 单文件桌面工作室，83,458,533 字节。
- `LabCapsule-0.11.0-ota.bin` — ESP32-S3 V0.11.0 应用 OTA 镜像，1,395,072 字节。
- `LabCapsule-0.7.0.apk` — 兼容的 Android 8.0+ 简体中文控制器；完整 V0.11 桌宠 UI 当前先在电脑端提供。

## SHA-256

```text
D8E725D116EB8E50D4BB892EDF22E4140671F39EB26F089AC86B689E7692EA87  LabCapsule-Studio-0.11.0.exe
3772405BC1B689142D61E499119280D77713A90B51416FABF943885A6BBC500F  LabCapsule-0.11.0-ota.bin
```

当前 EXE 没有 Authenticode 签名。请只从本仓库 GitHub Release 下载并核对 SHA-256；Windows SmartScreen 可能显示未知发布者。

## 更新与安装

1. 初次进入 V0.11 桌宠协议建议通过 USB 完整烧录：在 `firmware` 目录执行 `idf.py -p COM8 flash`。后续相同分区表版本可以使用 APK OTA 安装 `LabCapsule-0.11.0-ota.bin`。
2. 完整烧录不会格式化独立媒体/离线实验分区；不要运行 `erase-flash`，除非确实要删除 Wi-Fi、壁纸和离线实验数据。
3. 运行 `LabCapsule-Studio-0.11.0.exe`，选择 CH343/COM8 并连接。程序不会切换电脑 Wi-Fi，也不会连接设备的无网络热点。
4. 自动握手应返回 `PONG,LABCAPSULE,0.11.0-alpha` 与 `STATUS,READY,MPU=OK`；固件会在 STATUS 阶段透明重试尚未稳定的 MPU6050。
5. 进入“AI 桌宠”，点击“在 COM8 打开桌宠界面”。连接设备本身不会自动覆盖当前屏幕页面。
6. 如需在线 AI，填写 OpenAI 兼容 Endpoint、模型和 Key；DeepSeek 官方 Endpoint 的默认模型为 `deepseek-v4-flash`。Key 由当前 Windows 用户 DPAPI 加密。
7. Live2D 角色继续从用户目录加载。LabCapsule 不分发 Cubism Core、Hiyori 或其他第三方角色素材；首次使用须由素材权利人确认条款。

## 重点变化

- 设备新增独立桌宠界面、9 项动作白名单和底部 `216 × 64` 中文位图气泡。
- 电脑承担 AI、中文排版、脱敏和气泡渲染；ESP32 只负责可靠接收、本地动画和显示。
- 气泡使用 1728 字节、CRC32、64 字节节流分片；固件为中断上传加入 3 秒超时恢复。
- AI 能回答电脑资源、COM8、固件、实验参数、样本和数据质量问题；无 Key/网络失败时安全回退。
- 复杂任务可转交本机 Claude Code，但禁用全部工具、浏览器、MCP 和会话持久化，不能操作设备、网络或用户文件。
- Live2D 舞台可接收安全情绪/动作事件；Hiyori Pro 已实测 WebGL、Flick 与 `HAPPY + BOUNCE → FlickUp`。
- MPU6050 在启动窗口内尚未稳定时由正常 STATUS 握手自动恢复，不再要求普通用户手动进入诊断页。

## 验证摘要

- 43/43 Python 自动化测试通过；11 个桌面 Python 文件编译检查通过。
- Live2D Web 生产构建通过；npm 生产依赖审计为 0 漏洞。
- ESP-IDF 5.5.4 构建通过，应用为 `0x154980` 字节，3 MiB app 分区余 56%。
- COM8 完整烧录的 bootloader、app、partition table 和 OTA data 均完成哈希校验。
- 首次自动握手返回 `MPU=OK`；并发电脑心跳下中文气泡压力测试 50/50，0 CRC、0 协议错误。
- 最终 EXE 已完成 COM8、实体桌宠、DeepSeek 电脑状态问答和气泡同步验证。

完整步骤：

- `docs/V0.11.0_DEVICE_PET_AI_CLAUDE_ZH.md`
- `docs/V0.11.0_TEST_REPORT_ZH.md`
- `docs/V0.10.0_UNIFIED_PET_PACKAGE_TEST_ZH.md`
- `skills/labcapsule-pet-creator/SKILL.md`
