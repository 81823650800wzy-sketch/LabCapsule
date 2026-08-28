# LabCapsule

> Ask a question. Run an experiment.

LabCapsule 是基于 ESP32-S3 的便携式 AI 辅助实验组件。当前版本为 **V0.5.0 Alpha / Offline-capable Motion Experiment Prototype**，已经打通“自然语言问题 → 实验协议 → 六轴采集 → 在线直传或离线缓存 → CSV/分析”的设备侧和 Android 控制链路。

## V0.5.0 已实现

- 新增 8 MiB 磨损均衡离线实验分区和 `LCB1` 紧凑数据格式。没有 BLE/MQTT 实时接收端时，设备自动缓存时间戳与六轴数据；在线时直接推送，不重复写 Flash。
- 新增 BLE 实时实验通知与离线会话导出。APK“数据”页可读取容量/会话数、同步缓存、转换 CSV，并直接执行 RMS、Peak、FFT 与主频分析。
- 新增统一 `input_hub`。现有六按键、未来模拟摇杆、按键矩阵、I/O 扩展芯片及 BLE/HTTP 虚拟按键都映射为同一组逻辑动作；仅使用硬件即可调整采样率/时长、开始、停止或中止实验。
- 固件串口输出改为非阻塞，避免没有 USB 数据接收端时拖慢采样；离线会话在采样任务启动前建立，消除开头样本竞态。
- APK 明确说明 ESP32-S3 仅支持 2.4 GHz Wi-Fi。只有纯 5 GHz 网络时，`staConnected=false`、`staIp=0.0.0.0` 是硬件能力边界，BLE 控制、传感器扫描、实验与离线同步仍可使用。

V0.4.0 的界面与媒体能力继续保留：

- APK 主导航重构为“首页 / 实验 / 数据 / AI / 设置”：首页提供实验快捷入口，实验页负责协议与采集，数据页保存记录并分析 CSV；设备、屏幕和固件均归入设置且默认折叠。
- 首页内置桌面振动、碰撞峰值和姿态稳定三种真实 Experiment Protocol；自定义实验支持 10–500 Hz、1–3600 秒。
- 数据页可导入串口 CSV，计算六轴 RMS、绝对峰值，并对加速度合量执行 Hann 窗 FFT 和主频估计；实验元数据最多保存 50 条并可分享。
- GIF 先在手机端一次性裁剪、抽帧、RGB332 量化和差分编码，缓存到 APK 私有目录；ESP32 仍不存储 GIF。
- 新增 Android 前台播放服务、CPU 唤醒锁和 Wi-Fi 高性能锁。预处理完成后关闭或划掉 APK，GIF 仍继续播放，并可从系统常驻通知停止；系统“强行停止”应用仍会终止服务。
- GIF 后续帧新增 `delta332` 稀疏变化编码，只发送“跳过长度 + 连续变化像素”，不再把变化矩形中的未变化像素重复发送。Wi-Fi 目标间隔 90 ms，BLE 目标间隔 180 ms，并限制缓存帧数以平衡手机内存、带宽和设备负载。

- ESP32-S3 + ST7789 240×320 + MPU6050，六按键与 USB 串口控制。
- 设备同时运行恢复热点和外部 Wi-Fi Station；配置一次后，手机可回到有互联网的正常 Wi-Fi。
- 局域网 HTTP API，以及由设备主动连接的 MQTT/mqtts 远程控制通道。
- BLE 5 控制、状态、OTA、图片/壁纸二进制分片传输和 CRC32 校验。
- 8 MiB PSRAM 双帧缓冲；画面在内存中合成后通过内部 DMA 小块覆盖，刷新不先清黑屏。
- JPG/PNG/WebP/GIF 在 APK 中先以可拖动、双指缩放的 3:4 编辑器裁剪；原文件不会直接发给 ESP32。
- 静态图片采用无损 RGB565/RLE565；GIF 基准帧使用 RGB332/RLE332，后续自动选择稀疏 `delta332`、RLE332 或 RGB332 中的最小结果。
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

2. 安装 `release/LabCapsule-0.5.0.apk`。首次进入“设置 → 设备与连接”，推荐选择：

   - BLE：点击扫描并允许“附近设备”权限；连接成功后直接点“蓝牙一键配网”；
   - 恢复热点：只在排障时连接 `LabCapsule-XXXX`，密码 `labcapsule`，地址 `http://192.168.4.1`。

3. 输入路由器 2.4 GHz SSID/密码并保存。手机始终留在正常联网 Wi-Fi；设备状态卡直接显示 `staConnected`、`staIp` 与失败原因。成功后点击“使用此局域网 IP”。

4. 在“AI”页填写 API Endpoint、模型和 Key，生成协议后点击“发送并开始实验”。Key 由 Android Keystore 加密，仅在手机端使用。

完整操作见 [V0.5.0 离线实验与硬件扩展指南](docs/V0.5.0_OFFLINE_HARDWARE_GUIDE_ZH.md)、[V0.4.0 实验、数据与后台 GIF 指南](docs/V0.4.0_EXPERIMENT_GIF_GUIDE_ZH.md)、[V0.3.3 蓝牙配网与连接排障](docs/V0.3.3_BLE_WIFI_QUICKSTART_ZH.md) 和 [V0.3.2 壁纸与界面指南](docs/V0.3.2_WALLPAPER_STYLE_GUIDE_ZH.md)。

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
  → 按键 / HTTP / BLE 下发
  → MPU6050 / Mock 采样
  → BLE/MQTT 在线直传；无人接收时写入 8 MiB 离线分区
  → APK 同步为 CSV，或 USB 串口实时保存
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

2026-08-28 已在 COM8 的 ESP32-S3 rev 0.2 / 16 MiB Flash / 8 MiB Octal PSRAM 上完成 V0.5.0 构建、完整分区烧录和实机验证，串口启动标识为 `BOOT,LABCAPSULE,0.5.0-alpha`。100 Hz × 2 秒离线实验得到串口 200 条、缓存 200 条、丢样 0；BLE 在线实验收到 200/200 个通知且不新增离线会话；3 个缓存会话共 8,208 字节已通过 BLE 完整导出并逐头校验。BLE `SENSORS` 返回 I²C `0x68`，但 `WHO_AM_I=0x70` 与标准 MPU6050 标识不一致，正式采集前仍应确认模块型号。纯 5 GHz 网络无法被 ESP32-S3 Station 使用，设备会保持 BLE 可用并在失败四次后恢复热点。

## 安全边界

- APK 中的 API Key、Wi-Fi 和 MQTT 密码使用 Android Keystore 加密保存。
- 设备状态接口不回传密码；MQTT 支持 `mqtts://` 并使用 ESP-IDF CA 证书包。
- 恢复热点与局域网 HTTP API 面向受信任本地网络，V0.5.0 尚未提供逐设备 HTTP 登录或托管云端中继服务。
- Android 系统不允许普通应用静默安装 APK；自动更新会检查并下载，最终安装仍需用户确认。

## License

TBD
