# LabCapsule

> Ask a question. Run an experiment.

LabCapsule 是基于 ESP32-S3 的便携式 AI 辅助实验组件。当前版本为 **V0.3.3 Alpha / Motion Experiment Prototype**，已经打通“自然语言问题 → 实验协议 → 六轴采集 → CSV/分析”的设备侧和 Android 控制链路。

## V0.3.3 已实现

- ESP32-S3 + ST7789 240×320 + MPU6050，六按键与 USB 串口控制。
- 设备同时运行恢复热点和外部 Wi-Fi Station；配置一次后，手机可回到有互联网的正常 Wi-Fi。
- 局域网 HTTP API，以及由设备主动连接的 MQTT/mqtts 远程控制通道。
- BLE 5 控制、状态、OTA、图片/壁纸二进制分片传输和 CRC32 校验。
- 8 MiB PSRAM 双帧缓冲；画面在内存中合成后通过内部 DMA 小块覆盖，刷新不先清黑屏。
- JPG/PNG/WebP/GIF 在 APK 中先以可拖动、双指缩放的 3:4 编辑器裁剪；原文件不会直接发给 ESP32。
- GIF 由手机解码、RGB332 量化、变化区域检测和 RLE 压缩；未变化帧跳过，ESP32 只解压并显示当前区域，不保存 GIF。
- 静态图片采用无损 RGB565/RLE565，GIF 首帧最坏 76,800 字节、后续仅传变化矩形，显著低于旧版每帧 153,600 字节。
- 壁纸成为主页、设置和开发诊断页的真实底层；临时图片/GIF 也作为动态壁纸叠加 HUD，不再进入孤立的纯图片页。
- APK 与 ST7789 使用一致的原创工业街机主题，内置街机黄黑、信号红灰、冷蓝录像三套预设。
- 壁纸可见度、设备面板遮罩、设备 HUD/文字、APK 面板/导航玻璃均可通过 0–100 连续滑杆直接调整。
- 可注册的传感器驱动接口，覆盖 I²C、SPI、UART、ADC、OneWire；内置常见 I²C 设备发现。
- 默认中文 Android 8.0+ APK，透明液态滚轮导航、页面过渡、屏幕遥控、传感器发现、Wi-Fi/BLE OTA；设备页直接显示外部 Wi-Fi 是否已配置、是否连接和局域网 IP。
- APK 内配置 OpenAI 兼容 API（默认 DeepSeek），严格校验 Experiment Protocol，一键下发；失败时使用本地模板。
- 从 GitHub Releases 检查 APK 与 OTA 固件更新。
- 仅连接 BLE 时即可下发外部 2.4 GHz Wi-Fi、读取 `staConnected/staIp`、恢复热点并扫描 I²C；外网连接连续失败会自动退回可见的恢复热点。
- APK 屏幕镜像严格保持 240×320 比例，每秒同步设备页面、实验状态、I²C、背光与 HUD；避免传输整块帧缓冲占满 BLE。
- 修复选择图片/GIF 时可能出现的 `divide by zero`，并为无效图片尺寸增加前置校验。

## 快速开始

1. 首次安装或分区表发生变化时，用 USB 完整烧录：

   ```powershell
   . 'D:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1'
   cd <仓库目录>\firmware
   idf.py build
   idf.py -p COM8 flash monitor
   ```

2. 安装 `release/LabCapsule-0.3.3.apk`。首次进入“设备”，推荐选择：

   - BLE：点击扫描并允许“附近设备”权限；连接成功后直接点“蓝牙一键配网”；
   - 恢复热点：只在排障时连接 `LabCapsule-XXXX`，密码 `labcapsule`，地址 `http://192.168.4.1`。

3. 输入路由器 2.4 GHz SSID/密码并保存。手机始终留在正常联网 Wi-Fi；设备状态卡直接显示 `staConnected`、`staIp` 与失败原因。成功后点击“使用此局域网 IP”。

4. 在“AI”页填写 API Endpoint、模型和 Key，生成协议后点击“发送并开始实验”。Key 由 Android Keystore 加密，仅在手机端使用。

完整操作见 [V0.3.3 蓝牙配网与连接排障](docs/V0.3.3_BLE_WIFI_QUICKSTART_ZH.md)、[V0.3.2 壁纸与界面指南](docs/V0.3.2_WALLPAPER_STYLE_GUIDE_ZH.md) 和 [V0.3.1 基础使用指南](docs/V0.3.1_USER_GUIDE_ZH.md)，系统边界与扩展方式见 [V0.3.0 架构说明](docs/V0.3.0_ARCHITECTURE.md)。

## 冻结引脚

| 模块 | 信号 | ESP32-S3 |
|---|---|---:|
| MPU6050 / 扩展 I²C | SDA / SCL / INT | GPIO8 / GPIO9 / GPIO2 |
| ST7789 | SCK / MOSI / CS | GPIO12 / GPIO11 / GPIO10 |
| ST7789 | DC / RST / BL | GPIO7 / GPIO6 / GPIO5 |
| 按键 | UP / DOWN / LEFT / RIGHT / OK / BACK | GPIO14 / 15 / 16 / 17 / 18 / 13 |

按键统一为 `GPIO → 按键 → GND`，使用 `INPUT_PULLUP`；未按下 HIGH，按下 LOW。所有模块共地并使用 3.3 V 逻辑。

## 核心数据流

```text
自然语言问题
  → APK 内 AI / 本地回退模板
  → Experiment Protocol JSON
  → HTTP 或 BLE 下发
  → MPU6050 / Mock 采样
  → USB 串口实时六轴数据
  → PC 保存 CSV
  → RMS / Peak / FFT / 主频与实验组比较
```

## 目录

```text
android/                 无 Gradle 依赖的原生 Android 客户端与构建脚本
firmware/                ESP-IDF 5.5 固件、分区表和默认配置
docs/                    架构、使用指南和开发日志
release/                 可发布 APK、OTA bin 与校验值
SPEC_V0.1.md             初始产品规格（历史基线）
```

## 当前实机状态

2026-08-27 已在 COM8 的 ESP32-S3 rev 0.2 / 16 MiB Flash / 8 MiB Octal PSRAM 上完成 V0.3.3 构建和完整烧录。实测 BLE `STATUS` 返回恢复热点状态、`staConnected=false`、`staIp=0.0.0.0`；BLE `SENSORS` 返回 I²C `0x68`；错误外网配置四次失败后自动退回纯 AP，Windows 在不切换当前联网 Wi-Fi 的情况下重新扫描到 `LabCapsule-6625`，信号 99%。I²C 地址 `0x68` 有响应，但 `WHO_AM_I=0x70` 与标准 MPU6050 标识不一致，正式采集前仍应确认模块型号。

## 安全边界

- APK 中的 API Key、Wi-Fi 和 MQTT 密码使用 Android Keystore 加密保存。
- 设备状态接口不回传密码；MQTT 支持 `mqtts://` 并使用 ESP-IDF CA 证书包。
- 恢复热点与局域网 HTTP API 面向受信任本地网络，V0.3.3 尚未提供逐设备 HTTP 登录或云端中继服务。
- Android 系统不允许普通应用静默安装 APK；自动更新会检查并下载，最终安装仍需用户确认。

## License

TBD
