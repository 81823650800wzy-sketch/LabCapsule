# LabCapsule 0.8.1 Alpha（Desktop First）

## 本次发布文件

- `LabCapsule-Studio-0.8.1.exe` — Windows 10/11 单文件桌面工作室，74,019,734 字节，内含 FFmpeg 视频解码组件。

本版没有改动设备协议、分区和 Android 客户端。继续使用 V0.7 配套文件：

- `LabCapsule-0.7.0.apk` — Android 8.0+ 简体中文控制器。
- `LabCapsule-0.7.0-ota.bin` — ESP32-S3 V0.7 固件 OTA 镜像。

## SHA-256

```text
8A54B8AE80C52A1C466882A1443B3A4C9F1A39D90AE351243CB280C2B3F7AAAE  LabCapsule-Studio-0.8.1.exe
```

## 更新与安装

1. 下载并运行 `LabCapsule-Studio-0.8.1.exe`，无需安装 Python。
2. 使用数据线连接 CH343/COM8；程序不会更改电脑 Wi-Fi，也不会连接设备的无网络恢复热点。
3. 设备继续运行 `0.7.0-alpha` 固件即可；不需要重新烧录，也不会改变已有壁纸、动画和离线实验。
4. Android 继续使用 `LabCapsule-0.7.0.apk`。V0.8 先完成电脑端，后续按 Pet Event V1 扩展为电脑/手机双端角色。

## 重点变化

- 实时图表增加八通道选择、加速度/角速度双 Y 轴、精确鼠标坐标、X/Y 缩放、平移、实时跟随与窗口切换。
- 图表最多保留 100,000 点，使用保峰值像素抽稀和约 30 FPS 合并重绘；CSV 仍保留原始样本。
- 损坏串口数据、`NaN/Inf` 和非法时间戳会在写入图表与 CSV 前被拒绝。
- 新增理解设备上下文的 AI 桌宠、原创动态角色和可拖动桌面悬浮层。
- 支持 OpenAI 兼容 Endpoint/模型，默认 DeepSeek；无 Key 或断网时使用本地规则回退。
- API Key 由 Windows DPAPI 加密，最近记忆有界、可关闭和清除；常见敏感字段落盘前脱敏。
- AI 没有直接实验、网络或固件工具，只能提供说明和提出建议。
- 提供 Pet Event V1 JSON Schema、主动 Agent 租约和动作确认设计，为后续 Android 双端接入奠定协议基础。

COM8 已验证返回 `PONG,LABCAPSULE,0.7.0-alpha`、`READY`、`MPU=OK`、`MOCK=OFF`；屏幕诊断、背光、主机信息、AI 通知与连续 25 次 PING 通过，结束后恢复原壁纸。测试没有启动实验、上传媒体或更改网络。105,000 点/500 Hz 图表压力、AI 本地与 OpenAI 兼容模拟服务、九种情绪、DPAPI、媒体/GIF/MP4、CSV、通知权限回退和打包后 EXE 均已验证。完整说明见 `docs/V0.8.0_INTERACTIVE_CHART_AI_PET_ZH.md`。
