# LabCapsule ESP-IDF Firmware 0.3.0-alpha

目标硬件：ESP32-S3，16 MiB Flash、8 MiB Octal PSRAM、ESP-IDF 5.5.4。

## 构建与首次烧录

```powershell
. 'D:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1'
cd <仓库目录>\firmware
idf.py build
idf.py -p COM8 flash monitor
```

首次安装、从 0.1.x 升级或修改分区表时必须执行完整 `flash`。之后可以在 APK 中选择 `LabCapsule-0.3.0-ota.bin` 经 Wi-Fi/BLE 更新。不要为普通升级运行 `erase-flash`，它会清除 NVS 配置和持久壁纸。

## 分区与内存

- `ota_0` / `ota_1`：各 3 MiB；当前固件约 1.25 MiB，余量约 58%。
- `wallpaper`：256 KiB，使用双槽提交头，完整校验后才切换。
- 两张 240×320 RGB565 帧缓冲和媒体接收帧位于 PSRAM。
- 显示合成后以 8 行内部 DMA 缓冲覆盖 ST7789，不先擦黑屏，也不让 SPI DMA 直接访问大块 PSRAM。

## 联网

启动后进入 AP+STA 模式：

- 恢复热点 `LabCapsule-XXXX`，密码 `labcapsule`，HTTP `192.168.4.1`；
- 保存外部 Wi-Fi 后自动连接，`GET /api/status` 返回 `staIp`；
- 可保留恢复热点，防止配置错误后失联；
- 可配置设备主动连接 MQTT/mqtts Broker，无需在家庭路由器开放入站端口。

远程主题：

```text
订阅：<topic-prefix>/<device-id>/command
发布：<topic-prefix>/<device-id>/status
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
| POST | `/api/experiment?rate=200&duration=20` | 校验并开始实验 |
| POST | `/api/media/frame?duration=100` | 临时 RGB565 帧，不写 Flash |
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
| `0002` | command | 屏幕/按键命令，含 `START:200:20` |
| `0003` | status | 状态读取/通知 |
| `0004` | OTA control | `BEGIN:size`、`END`、`ABORT` |
| `0005` | OTA data | 固件分片 |
| `0006` | file control | 媒体开始、结束、CRC32 |
| `0007` | file data | RGB565 分片 |

媒体控制帧：`BEGIN:FRAME:153600:<duration-ms>:<crc32>` 或 `BEGIN:WALLPAPER:153600:0:<crc32>`，随后写入数据分片并发送 `END`。

## 传感器扩展

`sensor_hub.h` 定义统一的 `sensor_driver_t`：设备标识、显示名称、总线类型、地址、能力、探测、启动与 JSON 采样回调。总线类型预留 I²C、SPI、UART、ADC、OneWire，最多注册 16 个驱动。

内置发现项：MPU6050、BME280/BMP280、SHT3x、INA219、ADS1115、VL53L0X。新增驱动时实现回调并调用 `sensor_hub_register()`，不需要修改应用层状态机。

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
HELP
```

样本格式：

```text
DATA,timestamp_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps
```

ST7789 是只写 SPI，固件只能确认控制器和 DMA 接受发送，不能从面板读取物理确认。开发诊断页会显示固定引脚和常见故障方向。
