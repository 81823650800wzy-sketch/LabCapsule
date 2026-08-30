# LabCapsule

> Ask a question. Run an experiment.

LabCapsule 是基于 ESP32-S3 的便携式 AI 辅助实验组件。当前版本为 **V0.9.0 Alpha / Network Avatar（Desktop First）**，已经打通“自然语言问题 → 实验协议 → 六轴采集 → 在线直传或离线缓存 → CSV/分析”，并加入可精确检查的实时曲线、理解设备上下文的 AI 桌宠和安全的网络形象导入。V0.9.0 桌面端继续兼容 V0.7 固件与 Android APK。

## V0.9.0 新增

- AI 桌宠支持任意 HTTPS PNG/JPG/WebP/GIF 图片直链，并内置 DiceBear `Pixel Art / Lorelei / Thumbs / Shapes` 四个 CC0 预设和稳定种子生成。
- 网络文件在电脑端执行 MIME/内容格式、12 MiB、2048²、像素、120 帧、总解码量和 SHA-256 检查；公网强制 HTTPS，失败不会覆盖旧形象。
- 只缓存当前有效形象，退出软件后仍可自动恢复；GIF 使用文件自己的逐帧时间轴，最快 33 ms/帧，不依赖手机后台传帧。
- 同一形象同步到 AI 主舞台与可拖动桌面悬浮层，并可一键载入 240×320 屏幕工作室，由用户确认裁剪与 USB 上传。
- 形象库内提供 DiceBear、VRoid、VRoid Hub、Live2D 官方入口和授权提示；VRoid/Live2D 只接受预先导出的图片，不运行 VRM/moc3。
- 新增网络、缓存、安全和 GUI 集成测试；继续回归实验数据、交互图表、AI 本地/在线兼容路径。

完整说明和可直接复制的网址见 [V0.9.0 网络形象指南](docs/V0.9.0_NETWORK_AVATAR_GUIDE_ZH.md)。

## V0.8.1 回归修复

- 完成 AI 桌宠本地/在线兼容链路、COM8 屏幕桥、105,000 点图表压力、媒体、CSV、通知回退和打包 EXE 的全面测试。
- 串口 `DATA` 统一在入库前解析；损坏时间戳、负时间戳和 `NaN/Inf` 不再进入图表或 CSV。
- 新增数据解析回归测试，自动测试总数由 5 项增至 7 项。

## V0.8.0 新增

- Windows 实验图表扩展为 AX/AY/AZ、GX/GY/GZ、`|A|`、`|G|` 八通道；加速度与角速度使用独立 Y 轴，鼠标悬停可读取最近真实样本的横坐标、原始微秒时间戳、纵坐标与单位。
- 支持滚轮缩放时间轴、`Ctrl + 滚轮`缩放 Y 轴、左键拖动平移、双击复位、2–60 秒/全部窗口与实时跟随。
- 最多保留 100,000 点，约 30 FPS 合并重绘并按画布像素抽稀；显示抽稀不会影响原始 CSV 导出。
- 串口 `DATA` 在写入图表和 CSV 前统一验证时间戳、六轴数值与有限性，损坏行、`NaN/Inf` 和负时间戳不会污染实验结果。
- 新增电脑端 AI 桌宠：原创动态胶囊角色、对话、桌面悬浮层、设备/实验事件反应、运动统计上下文、本地规则回退和有界记忆。
- OpenAI 兼容 Endpoint、模型与角色设定可配置，默认兼容 DeepSeek；API Key 使用当前 Windows 用户的 DPAPI 加密。
- AI 没有系统命令和直接设备控制工具。开始/中止实验、网络设置与固件更新继续由用户在专用界面确认。
- 参考 [Project AIRI](https://github.com/moeru-ai/airi) 的角色/Agent/舞台分层，按 LabCapsule 的 USB 实验链路和 240×320 小屏做轻量改良；提供共享 Pet Event Schema，为后续 Android 双端接入预留一致协议。

完整说明见 [V0.8.0 交互图表与 AI 桌宠设计](docs/V0.8.0_INTERACTIVE_CHART_AI_PET_ZH.md)。

## V0.7.0 新增

- 修正 ST7789 初始反色：启动默认为 `INVERT=OFF`，仍保留诊断页和手动反色命令。
- GIF 速度改为真实 `1–8 FPS`，不再使用容易误解的百分比。COM8 真机从 4 FPS 调为 8 FPS 后，帧周期实测由 250 ms 变为 125 ms。
- GIF 改为“一次预处理、一次上传、设备本地播放”：APK/电脑负责裁剪、抽帧、RGB332 量化和差分压缩；ESP32 的 8 MiB FAT 分区只保存一个 `current.lcg`。退出 APK、手机锁屏或设备重启后仍可播放。
- 当前媒体采用互斥替换策略：保存新图片会删除旧 GIF，保存新 GIF/视频会清除旧壁纸标记；LCG 先写临时文件、校验容器和 CRC32，再原子替换，失败保留旧动画。
- 手机裁剪器支持 `25%–800%` 缩放、单指平移和双指缩放。小于覆盖比例时以黑色或白色补底，不再只能放大；选择异常媒体的零尺寸路径有前置保护。
- 新增 Windows `LabCapsule Studio`：COM8/CH343 自动优先、电脑 CPU/内存/磁盘自动上屏、Windows 通知镜像、240×320 预览、图片/GIF/视频/透明桌宠合成、界面遥控、实时六轴曲线和 CSV 导出。
- 新增 USB 二进制媒体协议 `UPLOAD,CLIP|WALLPAPER,SIZE,CRC32`。电脑不需要加入设备的无网络热点，也不会改变当前 Wi-Fi。
- 图片、GIF 与视频的裁剪、解码、缩放、桌宠合成和压缩都由手机/电脑承担；ESP32 只做流式校验、持久化、解码和绘制，避免主控过载。
- APK 状态卡明确显示设备当前媒体、本地 GIF 播放状态与 FPS；蓝牙/Wi-Fi 图片和 GIF 上传继续保留。

完整说明见 [V0.7.0 本地媒体与桌面工作室指南](docs/V0.7.0_LOCAL_MEDIA_DESKTOP_GUIDE_ZH.md)。

## V0.6.0 已实现

- 设备可在“闲置信息”和“实验直传”两种工作模式间切换。闲置屏每秒显示运行时间、内部 RAM、PSRAM、离线存储、BLE、外部 Wi-Fi、MQTT 和一条通知摘要；实验启动时自动返回直传界面。
- APK 首页与折叠的设备设置均可切换模式、填写闲置提示并读取硬件使用情况。Android 通知访问为可选授权，开启后仅在闲置模式转发摘要；隐私模式只显示应用名，实验和 GIF 播放期间自动暂停镜像。
- V0.6 的手机后台逐帧 GIF 与百分比调速已在 V0.7 被设备本地动画和 1–8 FPS 取代。
- BLE 新增 `MODE:IDLE`、`MODE:EXPERIMENT`、`NOTICE:title|message`、`HARDWARE`；HTTP 新增 `POST /api/mode`。蓝牙状态生成改为无动态分配的紧凑路径，修复模式切换时的堆损坏重启。
- 2026-08-28 真机回归：模式/硬件往返连续 3 次通过；Mock 链路 100 Hz × 2 秒收到 200/200 个 BLE 实时样本且未新增离线会话；原有 3 组、507 个离线样本完整导出。

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
- V0.4 的手机端逐帧发送链路作为历史兼容代码保留；V0.7 默认把压缩后的当前动画一次性写入设备。
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

2. 安装 GitHub Release 中的 `LabCapsule-0.7.0.apk`。首次进入“设置 → 设备与连接”，推荐选择：

   - BLE：点击扫描并允许“附近设备”权限；连接成功后直接点“蓝牙一键配网”；
   - 恢复热点：只在排障时连接 `LabCapsule-XXXX`，密码 `labcapsule`，地址 `http://192.168.4.1`。

3. 输入路由器 2.4 GHz SSID/密码并保存。手机始终留在正常联网 Wi-Fi；设备状态卡直接显示 `staConnected`、`staIp` 与失败原因。成功后点击“使用此局域网 IP”。

4. 在“AI”页填写 API Endpoint、模型和 Key，生成协议后点击“发送并开始实验”。Key 由 Android Keystore 加密，仅在手机端使用。

完整操作见 [V0.7.0 本地媒体与桌面工作室指南](docs/V0.7.0_LOCAL_MEDIA_DESKTOP_GUIDE_ZH.md)、[V0.6.0 工作模式与通知指南](docs/V0.6.0_IDLE_GIF_MODE_GUIDE_ZH.md)、[V0.5.0 离线实验与硬件扩展指南](docs/V0.5.0_OFFLINE_HARDWARE_GUIDE_ZH.md) 和 [V0.3.3 蓝牙配网与连接排障](docs/V0.3.3_BLE_WIFI_QUICKSTART_ZH.md)。

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
desktop/                 Windows 可视化控制器、媒体处理器与 EXE 构建脚本
firmware/                ESP-IDF 5.5 固件、分区表和默认配置
docs/                    架构、使用指南和开发日志
release/                 可发布 APK、OTA bin 与校验值
SPEC_V0.1.md             初始产品规格（历史基线）
```

## 当前实机状态

2026-08-28 已在 COM8 的 ESP32-S3 rev 0.2 / 16 MiB Flash / 8 MiB Octal PSRAM 上完成 V0.7.0 完整烧录和实机验证，串口标识为 `PONG,LABCAPSULE,0.7.0-alpha`。默认反色关闭；原壁纸先完整备份，测试动画通过 USB 上传、CRC 校验、本地播放、4→8 FPS 即时变速和断电重启自启动后已删除，原壁纸随后逐字节分区恢复并确认可用。桌面 UI、静态图/GIF/MP4/桌宠处理、APK v2/v3 签名和固件构建均已通过。纯 5 GHz 网络仍无法被 ESP32-S3 Station 使用，BLE 和 USB 不受影响。

## 安全边界

- APK 中的 API Key、Wi-Fi 和 MQTT 密码使用 Android Keystore 加密保存。
- 设备状态接口不回传密码；MQTT 支持 `mqtts://` 并使用 ESP-IDF CA 证书包。
- 恢复热点与局域网 HTTP API 面向受信任本地网络，V0.7.0 尚未提供逐设备 HTTP 登录或托管云端中继服务。
- 手机通知读取必须由用户在 Android 系统设置中单独授权；通知正文只在闲置模式下发送到所选设备通道，可随时关闭或启用只显示应用名的隐私模式。
- Android 系统不允许普通应用静默安装 APK；自动更新会检查并下载，最终安装仍需用户确认。

## License

TBD
