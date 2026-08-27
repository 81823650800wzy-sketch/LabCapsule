# LabCapsule 0.3.2 Alpha

## 发布文件

- `LabCapsule-0.3.2.apk` — Android 8.0+ 中文控制器，57,754 字节。
- `LabCapsule-0.3.2-ota.bin` — ESP32-S3 应用 OTA 镜像，1,323,872 字节。

## SHA-256

```text
C13E80CA7275306B76CCD3771F962565DF2B7EE17C8A5D2C08DB35081F7C2FE8  LabCapsule-0.3.2.apk
C369AD6EE5C1A331E5213C34AC6352F50F358429D710819F2256553545F33CEA  LabCapsule-0.3.2-ota.bin
```

## 安装说明

从 0.1.x 或旧分区表升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 bootloader、OTA data 和新分区表。完成首次完整烧录后，后续版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.3.2 将静态图片/GIF 改为真正的持久/动态壁纸底层；APK 与 ST7789 统一为原创工业街机风格，并支持壁纸、设备面板、设备 HUD、APK 玻璃层四路 0–100 连续透明度。
