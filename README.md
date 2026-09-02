# LabCapsule

> Ask a question. Run an experiment.

LabCapsule 是基于 ESP32-S3 的便携式 AI 辅助实验组件。当前双端版本为 **V1.3.0 Alpha / AI Experiment Orchestrator**：用户用自然语言提出实验后，在线 AI 会真实规划传感器、采样率、时长、分析方法和参考资料需求；APK 在 I²C 与传输预检通过、设备确认 START 后才进入采集，并实时显示用时、样本和终止状态。

## V1.3.0 双端新增

- 所有测量类输入先进入 OpenAI 兼容 AI 规划，输出经过严格 JSON 白名单校验；AI 未配置或离线时明确显示本地安全回退。
- 当前只允许真实执行 MPU6050 六轴驱动，采样率 10–500 Hz、时长 1–1800 秒（手工协议最高 3600 秒）、单次最多 500000 点；不支持的物理量会要求澄清。
- 启动前刷新 I²C 扫描并确认 MPU6050 在线；HTTP 必须收到 `ok=true`，BLE 必须成功写入 START，才开始计时和记录历史。
- 数据页实时显示 `已用时间 / 计划时间 / 当前样本 / 预计样本`，提供“终止实验”；终止前的数据继续保存、分析并标为 `aborted`。
- AI 可选择无需参考、电脑 Claude 推理或电脑联网检索；联网检索仅开放 `WebSearch/WebFetch`，不开放 Shell、文件读写或本机控制。

完整操作见 [V1.3 AI 真实实验使用指南](docs/V1.3.0_AI_EXPERIMENT_GUIDE_ZH.md)。

## V1.2.0 双端新增

- APK 更新显示真实字节与百分比，退出再进入可继续追踪系统下载任务。
- 对话按用户内容命名并折叠，支持新对话、模糊搜索和自动定位；用户与 AI 气泡方向和配色不同。
- Live2D、人设、静态预览和可选语音包组成完整角色卡，通过用户私有仓库的小索引与 Release 资产在 PC/手机同步；按 SHA-256 本地缓存。
- Android 与 Windows 都能横向预览角色卡，并可单独勾选替换形象、人设或语音包。
- Studio 手机桥默认关闭；用户在电脑开启后，手机必须输入 10 分钟有效的一次性码，才可读取电脑/设备状态并把复杂问题交给电脑端 Claude。

完整操作见 [V1.2 角色卡与手机电脑协同指南](docs/V1.2.0_ROLECARD_COLLAB_GUIDE_ZH.md)。

## V1.1.0 Android 新增

- 导航收敛为“首页 / 数据 / 桌面 / 设置”；首页只显示 Hiyori Live2D 与 AI 对话，所有配置默认折叠并支持模糊搜索。
- “马上帮我测试 10 秒的桌面震动情况”会由本地意图执行器选择 MPU6050、启动采集、绘制曲线、保存 CSV、执行 RMS/Peak/FFT 并回复结果。
- 数据曲线支持双指缩放、拖动、逐点六轴读数、PNG/CSV 导出；历史按日期折叠并可搜索。
- 支持用自然语言对 AX/AY/AZ/GX/GY/GZ 执行软件标定，后续 CSV、曲线和分析统一使用回正数据。
- 对话、记忆和实验数据本地优先；联网后可每 15 分钟同步到用户配置的私有 GitHub 仓库。
- 四个页面均显示连接状态，断开时优先给出 BLE 和局域网连接入口。

完整操作见 [V1.1 AI 测量工作台使用指南](docs/V1.1.0_AI_MEASUREMENT_GUIDE_ZH.md)。

## V1.0.0 新增

- 从 ESP32-S3 eFuse MAC 派生稳定 `deviceId`，不再用易变的 COM 号或 IP 区分用户设备；COM8 实机为 `lc-000000000000`。
- Windows、Android 和实体屏统一使用模型内容 ID。现有 Hiyori Free 为 `live2d-000000000000`；旧版按路径生成的 `local-*` 会自动迁移。
- Windows Studio 支持 USB、不会切换电脑网络的局域网 HTTP，以及完整 BLE 控制/状态/实验/媒体；默认导航精简为“实验助手 / 实验数据 / 设置”。
- Android V1 增加 Hiyori 对话、系统语音入口、设备身份、私有记忆同步和 Live2D 完整文件夹导入；设备/屏幕/固件继续位于默认折叠的设置区。
- 记忆使用用户自己的私有 GitHub 仓库，按 `memory/devices/<deviceId>/snapshot.json` 跨电脑和手机合并；Token/API Key 分别由 DPAPI 和 Android Keystore 加密，公开仓库被拒绝。
- 设备本地保存并循环播放当前 Hiyori 代理或 GIF，退出 APK 后不停止；AI 只发送有界动作与 216×64 气泡，不向 ESP32 逐帧推 Live2D。
- 新增按需上下文 Skill 和机器可读设备/记忆/角色 Schema。AI 只取相关组件、连接、实验和最多 12 条记忆，避免把整个仓库装入提示。
- 修复活动 MPU 与扩展 I²C 探测争用；COM8 和 BLE 均返回 1 个 0x68 传感器。纯 5 GHz 下明确显示 `staConnected=false / staIp=0.0.0.0`，USB/BLE/离线实验仍正常。
- Windows 麦克风支持 16 kHz 转写；Android 使用系统语音识别。硬件声明 `MIC_PORT` 扩展契约，后续 I²S 麦克风由连接端承担转写和 AI 算力。

完整步骤见 [V1.0 统一随身实验助手指南](docs/V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md)，构建与实机证据见 [V1.0 测试报告](docs/V1.0.0_TEST_REPORT_ZH.md)。

## V0.11.0 新增

- ST7789 新增独立实体桌宠页：角色由 ESP32 本地持续绘制，AI 中文回答显示在底部 `216 × 64` 气泡，不依赖电脑逐帧传屏。
- 桌面端新增电脑状态、设备/实验状态、实验设计和数据质量快捷问答；在线默认使用 DeepSeek `deepseek-v4-flash`，无网络或无 Key 时安全回退。
- 复杂任务可转交本机 Claude Code，但固定为单轮只读模式：禁用工具、MCP、浏览器、会话持久化和设备控制，并设置调用预算上限。
- 实体屏动作使用 9 项白名单；回答气泡先在电脑排版、脱敏并转成 1728 字节位图，再以 CRC32、64 字节节流分片传输。
- 固件为中断的二进制上传加入 3 秒恢复超时；COM8 并发发送电脑心跳时完成 50/50 气泡上传，0 CRC、0 协议错误。
- 自动握手中的 `STATUS` 会在 MPU6050 上电尚未稳定时透明重试探测，现场最终直接返回 `MPU=OK`，不再要求普通用户手工扫描。
- Hiyori Pro Live2D 已完成依赖识别、WebGL 动态渲染、点击动作和 `HAPPY + BOUNCE → FlickUp` 联动；第三方模型仍只保留在用户目录。

完整安装、AI、Claude、Live2D 与排障步骤见 [V0.11.0 使用手册](docs/V0.11.0_DEVICE_PET_AI_CLAUDE_ZH.md)，验证证据见 [V0.11.0 测试记录](docs/V0.11.0_TEST_REPORT_ZH.md)。

## V0.10.0 新增

- 新增桌宠角色包 V1：一个文件夹统一名称、人格、欢迎语和唯一主形象，AI 主舞台、桌面悬浮层与屏幕工作室不再分别选择角色。
- 应用可直接选择一个桌宠文件夹，或扫描其第一层包含多个角色包的桌宠库；只有一张 PNG/JPG/WebP/GIF 的文件夹也可零配置识别。
- Live2D Cubism `model3.json` 文件夹可零配置识别，运行前校验 moc3、PNG 纹理、physics/pose/display-info 与 motion3 依赖；独立 WebGL 舞台和透明置顶悬浮舞台共用同一动态模型。
- LabCapsule 不分发 Cubism Core；首次播放由用户本人确认适用条款后，才从 Live2D 官方地址加载固定版本 Core。第三方样本模型不会进入仓库、EXE 或 Release。
- 自动扫描 `%APPDATA%\LabCapsule\pets`、仓库 `pets` 和 EXE 同级 `pets`；选择会持久化并在启动时重新校验，文件失效时安全回退。
- 新增仓库 Skill `skills/labcapsule-pet-creator`，包含图片/GIF/Live2D 创建与验证脚本、角色包规范和分层测试清单；创建过程拒绝覆盖非空目录。
- 新增机器可读 JSON Schema、非法 UTF-8/路径逃逸/重复 ID 隔离、统一形象 GUI 烟雾测试和完整中文验收手册。

完整制作、安装与测试步骤见 [V0.10.0 统一桌宠测试手册](docs/V0.10.0_UNIFIED_PET_PACKAGE_TEST_ZH.md)。

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

2. Windows 端运行 GitHub Release 中的 `LabCapsule-Studio-1.3.0.exe`；Android 端安装 `LabCapsule-1.3.0.apk`。手机首次进入“设置 → 设备与连接”时，推荐选择：

   - BLE：点击扫描并允许“附近设备”权限；连接成功后直接点“蓝牙一键配网”；
   - 恢复热点：只在排障时连接 `LabCapsule-XXXX`，密码 `labcapsule`，地址 `http://192.168.4.1`。

3. 输入路由器 2.4 GHz SSID/密码并保存。手机始终留在正常联网 Wi-Fi；设备状态卡直接显示 `staConnected`、`staIp` 与失败原因。成功后点击“使用此局域网 IP”。

4. 在“设置”搜索“AI”，填写 Endpoint、模型和 Key；回到首页直接说出测量、标定或分析要求。Key 由 Android Keystore 加密，仅在手机端使用。

完整操作见 [V1.1 AI 测量工作台使用指南](docs/V1.1.0_AI_MEASUREMENT_GUIDE_ZH.md)、[V1.0 统一随身实验助手指南](docs/V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md) 和 [V0.3.3 蓝牙配网与连接排障](docs/V0.3.3_BLE_WIFI_QUICKSTART_ZH.md)。

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
knowledge/               可按需检索的组件、传感器与连接知识库
shared/                  设备身份、角色和记忆 JSON Schema
skills/                  桌宠创建及设备上下文访问 Skills
SPEC_V0.1.md             初始产品规格（历史基线）
```

## 当前实机状态

2026-09-01 已在 COM8 的 ESP32-S3 rev 0.2 / 16 MiB Flash / 8 MiB Octal PSRAM 上完成 V1.0.0 完整烧录和重启验收。串口返回 `PONG,LABCAPSULE,1.0.0-alpha,DEVICE=lc-000000000000`，MPU OK、扩展列表 count 1、Hiyori 代理开启；Windows BLE 也读到同一身份、角色和传感器。当前网络只有 5 GHz，因此状态如实为 `staConnected=false / staIp=0.0.0.0`，测试期间未连接无网络恢复热点。

## 安全边界

- APK 中的 API Key、Wi-Fi 和 MQTT 密码使用 Android Keystore 加密保存。
- 设备状态接口不回传密码；MQTT 支持 `mqtts://` 并使用 ESP-IDF CA 证书包。
- 恢复热点与局域网 HTTP API 面向受信任本地网络，V1.0 尚未提供逐设备 HTTP 登录或托管云端中继服务。
- 记忆同步只允许用户配置的私有 GitHub 仓库；硬件、仓库和状态接口都不保存或回传 GitHub Token/API Key。
- 手机通知读取必须由用户在 Android 系统设置中单独授权；通知正文只在闲置模式下发送到所选设备通道，可随时关闭或启用只显示应用名的隐私模式。
- Android 系统不允许普通应用静默安装 APK；自动更新会检查并下载，最终安装仍需用户确认。

## License

TBD
