# LabCapsule 0.3.3 Alpha

## 发布文件

- `LabCapsule-0.3.3.apk` — Android 8.0+ 中文控制器，61,848 字节。
- `LabCapsule-0.3.3-ota.bin` — ESP32-S3 应用 OTA 镜像，1,325,968 字节。

## SHA-256

```text
2FBA9E9AE0B5CF45422C77B3515876510EA1DFF4C44A9E93D27149C33E401162  LabCapsule-0.3.3.apk
841AD47CB94F11478458B7D501DA0601B7773D1F78787DDD7CCE25C6CA1FB090  LabCapsule-0.3.3-ota.bin
```

## 安装说明

从 0.1.x 或旧分区表升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 bootloader、OTA data 和新分区表。完成首次完整烧录后，后续版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.3.3 重点补齐 BLE 一键外部 Wi-Fi 配置、网络/IP 明示、I²C BLE 扫描、热点自动恢复、图片除零修复和 240×320 实时屏幕状态镜像。V0.3.2 的真实持久/动态壁纸、GIF 手机端差分压缩、原创工业街机风格和四路透明度控制继续保留。
