# LabCapsule

> Ask a question. Run an experiment.

LabCapsule 是基于 ESP32-S3 的便携式 AI 辅助实验组件。当前版本为 **V0.3.0 Alpha / Motion Experiment Prototype**，已经打通“自然语言问题 → 实验协议 → 六轴采集 → CSV/分析”的设备侧和 Android 控制链路。

## V0.3.0 已实现

- ESP32-S3 + ST7789 240×320 + MPU6050，六按键与 USB 串口控制。
- 设备同时运行恢复热点和外部 Wi-Fi Station；配置一次后，手机可回到有互联网的正常 Wi-Fi。
- 局域网 HTTP API，以及由设备主动连接的 MQTT/mqtts 远程控制通道。
- BLE 5 控制、状态、OTA、图片/壁纸二进制分片传输和 CRC32 校验。
- 8 MiB PSRAM 双帧缓冲；画面在内存中合成后通过内部 DMA 小块覆盖，刷新不先清黑屏。
- JPG/PNG/WebP 转换、静态壁纸和 GIF 流式播放。GIF 原文件保留在手机，ESP32 只持有当前帧，不写入 Flash。
- 可注册的传感器驱动接口，覆盖 I²C、SPI、UART、ADC、OneWire；内置常见 I²C 设备发现。
- 默认中文 Android 8.0+ APK，透明液态滚轮导航、页面过渡、屏幕遥控、传感器发现、Wi-Fi/BLE OTA。
- APK 内配置 OpenAI 兼容 API（默认 DeepSeek），严格校验 Experiment Protocol，一键下发；失败时使用本地模板。
- 从 GitHub Releases 检查 APK 与 OTA 固件更新。

## 快速开始

1. 首次安装或分区表发生变化时，用 USB 完整烧录：

   ```powershell
   . 'D:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1'
   cd <仓库目录>\firmware
   idf.py build
   idf.py -p COM8 flash monitor
   ```

2. 安装 `release/LabCapsule-0.3.0.apk`。首次进入“设备”，选择：

   - Wi-Fi：连接 `LabCapsule-XXXX`，密码 `labcapsule`，地址保持 `http://192.168.4.1`；
   - BLE：点击扫描并允许“附近设备”权限。

3. 在“设置”填入路由器 SSID/密码并保存。设备采用 AP+STA 模式接入外部 Wi-Fi；读取状态中的 `staIp`，把 APK 设备地址改为 `http://<staIp>`，手机即可回到正常网络。

4. 在“AI”页填写 API Endpoint、模型和 Key，生成协议后点击“发送并开始实验”。Key 由 Android Keystore 加密，仅在手机端使用。

完整操作见 [V0.3.0 中文使用指南](docs/V0.3.0_USER_GUIDE_ZH.md)，系统边界与扩展方式见 [V0.3.0 架构说明](docs/V0.3.0_ARCHITECTURE.md)。

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

2026-08-26 已在 COM8 的 ESP32-S3 rev 0.2 / 16 MiB Flash / 8 MiB Octal PSRAM 上完成构建、烧录和串口回归。ST7789 驱动、PSRAM、Wi-Fi AP+STA、BLE、Mock 采集和多页面刷新通过；当前实物的 MPU6050 在 GPIO8/9 上未应答，固件会在开发诊断界面和串口明确提示检查 VCC/GND/SDA/SCL。

## 安全边界

- APK 中的 API Key、Wi-Fi 和 MQTT 密码使用 Android Keystore 加密保存。
- 设备状态接口不回传密码；MQTT 支持 `mqtts://` 并使用 ESP-IDF CA 证书包。
- 恢复热点与局域网 HTTP API 面向受信任本地网络，V0.3.0 尚未提供逐设备 HTTP 登录或云端中继服务。
- Android 系统不允许普通应用静默安装 APK；自动更新会检查并下载，最终安装仍需用户确认。

## License

TBD
