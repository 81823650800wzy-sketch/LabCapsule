# LabCapsule 0.3.1 Alpha

## 发布文件

- `LabCapsule-0.3.1.apk` — Android 8.0+ 中文控制器，53,655 字节。
- `LabCapsule-0.3.1-ota.bin` — ESP32-S3 应用 OTA 镜像，1,319,904 字节。

## SHA-256

```text
632B01C1EC9B3F6CBDF5552D1124FD01DCFB52D446058395B5C980D87AF6FE47  LabCapsule-0.3.1.apk
809DE0CC3923618DD2408E5887C7F0AC8EE6EFA047E17F6FB08F1C8C9808706C  LabCapsule-0.3.1-ota.bin
```

## 安装说明

从 0.1.x 或旧分区表升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 bootloader、OTA data 和新分区表。完成首次完整烧录后，后续版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.3.1 新增 APK 内触控裁剪、GIF RGB332/变化矩形/RLE 智能传输，以及设备页外部 Wi-Fi 连接状态与局域网 IP 的明确中文显示。
