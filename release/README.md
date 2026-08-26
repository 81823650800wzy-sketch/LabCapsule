# LabCapsule 0.3.0 Alpha

## 发布文件

- `LabCapsule-0.3.0.apk` — Android 8.0+ 中文控制器，45,463 字节。
- `LabCapsule-0.3.0-ota.bin` — ESP32-S3 应用 OTA 镜像，1,318,336 字节。

## SHA-256

```text
98E8C277358A510D35DAC4CADB5F772147E7DAF96791073E04216C43EE8E8D5B  LabCapsule-0.3.0.apk
82D87400E0DE9E16C9AFC0892452F7080F7456F028F6CF5F870914A000405D2B  LabCapsule-0.3.0-ota.bin
```

## 安装说明

从 0.1.x 或旧分区表升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 bootloader、OTA data 和新分区表。完成首次完整烧录后，后续版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。
