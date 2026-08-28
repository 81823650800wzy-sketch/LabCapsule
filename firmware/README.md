# LabCapsule ESP-IDF Firmware 0.6.0-alpha

目标硬件：ESP32-S3，16 MiB Flash、8 MiB Octal PSRAM、ESP-IDF 5.5.4。

## 构建与首次烧录

```powershell
. 'D:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1'
cd <仓库目录>\firmware
idf.py build
idf.py -p COM8 flash monitor
```

首次安装、从 0.4.x 及更早分区表升级时必须执行一次完整 `flash`，写入 `offline` 分区。0.5.0 可直接使用 `LabCapsule-0.6.0-ota.bin` 经 Wi-Fi/BLE 更新。不要为普通升级运行 `erase-flash`，它会清除 NVS 配置、持久壁纸和离线实验。

## 分区与内存

- `ota_0` / `ota_1`：各 3 MiB；当前固件 1,377,664 字节，余量约 56%。
- `wallpaper`：256 KiB，使用双槽提交头，完整校验后才切换。
- `offline`：8 MiB 磨损均衡 FAT。每个 `LCB1` 会话使用 32 字节头和每条 16 字节的时间戳/六轴定点样本；临时文件完成后再改名，异常断电时可恢复。
- 两张显示帧缓冲、独立动态媒体画布和最大 153,600 字节媒体接收区位于 PSRAM。GIF 差分只修改干净媒体画布，随后重新合成 HUD，避免把上一帧文字写进动画底图。
- 显示合成后以 8 行内部 DMA 缓冲覆盖 ST7789，不先擦黑屏，也不让 SPI DMA 直接访问大块 PSRAM。

## 联网

启动后进入 AP+STA 模式：

- 恢复热点 `LabCapsule-XXXX`，密码 `labcapsule`，HTTP `192.168.4.1`；
- 保存外部 Wi-Fi 后自动连接，HTTP 和 BLE 状态均返回 `staConfigured`、`staConnected`、`staIp`、`recoveryApActive` 与最近断开原因；
- Station 连续失败四次后自动退回纯恢复热点，防止错误配置造成热点长期不可见；新的 BLE 配网会重新启动 AP+STA；
- 可配置设备主动连接 MQTT/mqtts Broker，无需在家庭路由器开放入站端口。

远程主题：

```text
订阅：<topic-prefix>/<device-id>/command
发布：<topic-prefix>/<device-id>/status
数据：<topic-prefix>/<device-id>/data
```

命令与屏幕动作相同，例如 `home`、`developer`、`brightness_50`。mqtts 使用 ESP-IDF CA bundle。

## HTTP API

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/status` | 设备、显示、采样、AP/STA/MQTT 状态 |
| GET | `/api/network` | 脱敏配置和网络状态 |
| POST | `/api/network` | JSON 保存 Wi-Fi/MQTT/语言/亮度配置 |
| GET | `/api/sensors` | 扫描总线并返回传感器注册表 |
| POST | `/api/control?action=home` | 屏幕、按键和亮度动作 |
| GET/POST | `/api/display` | 读取/保存主题和壁纸、面板、HUD 透明度 |
| POST | `/api/experiment?rate=200&duration=20` | 校验并开始实验 |
| POST | `/api/mode` | 切换 `idle/experiment` 并设置闲置通知摘要 |
| GET | `/api/offline` | 流式导出所有离线 `LCB1` 会话 |
| POST | `/api/offline` | 清空已完成的离线会话 |
| POST | `/api/media/frame?duration=100&enc=delta332&x=0&y=0&w=240&h=320` | 临时整帧/局部差分帧，不写 Flash |
| POST | `/api/wallpaper` | 持久 RGB565 壁纸，固定 153600 字节 |
| POST | `/api/ota` | ESP-IDF 应用 bin，验证后切换 OTA 槽并重启 |

网络配置 JSON 示例：

```json
{
  "ssid": "Lab-WiFi",
  "password": "secret",
  "keepAp": true,
  "brightness": 90,
  "mqttUri": "mqtts://broker.example.com:8883",
  "mqttUser": "device-user",
  "mqttPassword": "secret",
  "mqttTopic": "labcapsule",
  "remote": true,
  "locale": "zh-CN"
}
```

## BLE GATT

服务 UUID：`6c430001-4c61-6243-6170-73756c650001`。

| 结尾 | 属性 | 功能 |
|---:|---|---|
| `0002` | command | 屏幕/按键命令，以及 `STATUS`、`SENSORS`、`AP:ON`、BLE Wi-Fi 配网 |
| `0003` | status | 状态读取/通知 |
| `0004` | OTA control | `BEGIN:size`、`END`、`ABORT` |
| `0005` | OTA data | 固件分片 |
| `0006` | file control | 媒体开始、结束、CRC32 |
| `0007` | file data | RGB565 分片 |
| `0008` | experiment data | 在线样本通知及离线会话分片读取 |

BLE 配网命令为 `WIFI:<base64-ssid>:<base64-password>`，使用标准 Base64 且不换行。SSID/密码不会出现在状态回包中。`STATUS` 回包包含精简设备渲染状态和完整网络状态；`HARDWARE` 返回运行时间、内部 RAM、PSRAM、离线存储和三种连接状态；`MODE:IDLE` / `MODE:EXPERIMENT` 切换工作模式；`NOTICE:title|message` 更新闲置摘要。`SENSORS` 会重新扫描 GPIO8/9 并只返回当前有响应的 I²C 设备。ESP32-S3 只能使用 2.4 GHz Wi-Fi，纯 5 GHz 环境应保留 BLE 通道。

BLE GATT 回调栈不再生成大状态后再用 cJSON 二次解析，而是直接构建小型设备/硬件 JSON。该无动态分配路径用于避免模式切换和频繁状态读取造成堆压力。

离线命令为 `OFFLINE:INFO`、`OFFLINE:OPEN`、`OFFLINE:CLOSE`、`OFFLINE:CLEAR`。打开导出后重复读取 `0008`：首字节 `0x20` 表示后续是数据，`0x21` 表示结束。在线通知首字节为 `0x10`，后接 `elapsed_us:uint32` 和六个 `int16`；加速度除以 4096，角速度除以 16。只有 BLE 通知或 MQTT 数据队列接受当前样本时才视为在线，否则该样本进入离线缓存。

媒体控制帧：`BEGIN:FRAME:<size>:<duration-ms>:<crc32>:<encoding>:<x>:<y>:<w>:<h>` 或 `BEGIN:WALLPAPER:153600:0:<crc32>:raw565:0:0:240:320`，随后写入数据分片并发送 `END`。旧版四字段 FRAME 控制帧仍按完整 `raw565` 兼容。

临时媒体支持 `raw565`、`rle565`、`rgb332`、`rle332` 和 `delta332`。RLE 格式使用一字节重复计数（1–255）加一个 RGB565 像素或 RGB332 像素。`delta332` 每条记录为小端 `skip:uint16`、`run:uint8` 和 `run` 个 RGB332 像素；`run=0` 表示仅跳过，支持跨越 65,535 个未变化像素。解码器只改写动态媒体画布中的变化像素，再统一合成 HUD。只有第一帧允许从任意页面提交完整区域；后续差分区域必须在媒体视图中，防止把局部数据叠到未初始化画面。

2026-08-27 的 BLE 实机验证中，240×320 单色 RLE332 基准帧为 604 字节；随后在 10×10 区域更新一个像素的 `delta332` 负载为 4 字节，串口分别记录 `ENC=3` 与 `ENC=4`。

外观设置 JSON：

```json
{"preset":0,"wallpaperOpacity":82,"panelOpacity":76,"hudOpacity":100}
```

`preset` 为 0–2，其余字段为 0–100。HTTP 与 BLE 会保存到 NVS；BLE/远程命令格式为 `STYLE:0:82:76:100`，USB 串口格式为 `STYLE,0,82,76,100`。持久壁纸、临时图片和 GIF 都先作为背景，再合成同一套 HUD。

## 传感器扩展

`sensor_hub.h` 定义统一的 `sensor_driver_t`：设备标识、显示名称、总线类型、地址、能力、探测、启动与 JSON 采样回调。总线类型预留 I²C、SPI、UART、ADC、OneWire，最多注册 16 个驱动。

内置发现项：MPU6050、BME280/BMP280、SHT3x、INA219、ADS1115、VL53L0X。新增驱动时实现回调并调用 `sensor_hub_register()`，不需要修改应用层状态机。

## 硬件输入与独立实验

`input_hub.h` 将物理来源统一为 `UP/DOWN/LEFT/RIGHT/OK/BACK`。当前 `gpio-buttons` 驱动使用冻结的 GPIO14/15/16/17/18/13；后续模拟摇杆、按键矩阵或 I/O 扩展器只需实现返回动作位图的 `poll` 回调并调用 `input_hub_register()`，无需复制界面状态机。最多可注册 8 个输入驱动，各驱动独立消抖。

主页中：左右调整采样率，上下调整时长，OK 开始；采集中 OK 正常停止，BACK 中止。因而设备在没有手机或电脑时也能完成实验。采样过程中如有 BLE 订阅或 MQTT 接收端则实时上传；没有接收端的样本写入离线分区，稍后由 APK 同步。

## 串口

460800 baud，8-N-1。主要命令：

```text
PING
STATUS
START[,RATE,DURATION]
STOP
ABORT
MOCK,ON|OFF
DISPLAY[,DEV|TEST|WALLPAPER|SETTINGS|HOME|INVERT|BL,ON|OFF]
MODE,IDLE|EXPERIMENT
NOTICE,TITLE,MESSAGE
HELP
```

样本格式：

```text
DATA,timestamp_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps
```

ST7789 是只写 SPI，固件只能确认控制器和 DMA 接受发送，不能从面板读取物理确认。开发诊断页会显示固定引脚和常见故障方向。
