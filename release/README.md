# LabCapsule 0.5.0 Alpha

## 发布文件

- `LabCapsule-0.5.0.apk` — Android 8.0+ 中文控制器，90,519 字节。
- `LabCapsule-0.5.0-ota.bin` — ESP32-S3 应用 OTA 镜像，1,377,664 字节。

## SHA-256

```text
1B0C7D5401328C5C8AB0C10E5714DD2157D36CB79AA6D76484D6F31A7845D74B  LabCapsule-0.5.0.apk
10D6ECFAC26B0F37D4EBC9BE9DB4FCE10741BBADFA721D169DABF7ED1DB03D0C  LabCapsule-0.5.0-ota.bin
```

## 安装说明

从 0.4.x 或更旧版本升级到 0.5.0 时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入新增的 8 MiB 离线实验分区。完成首次完整烧录后，后续同分区版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.5.0 增加统一硬件输入层、8 MiB 离线实验缓存、BLE 实时六轴通知、BLE/HTTP 缓存导出及 APK 端同步/CSV 分析。设备可完全依靠按键运行实验：有 BLE/MQTT 接收端时实时上传，没有接收端时自动缓存。APK 明确显示 `staConnected`、`staIp` 和 ESP32-S3 只支持 2.4 GHz 的限制；纯 5 GHz 环境仍可完整使用 BLE 功能。

实机基准：100 Hz × 2 秒离线采样为串口 200 / 缓存 200 / 丢样 0；BLE 在线通知 200/200 且不新增缓存会话。完整说明见 `docs/V0.5.0_OFFLINE_HARDWARE_GUIDE_ZH.md`。
