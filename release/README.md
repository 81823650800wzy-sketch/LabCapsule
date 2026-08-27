# LabCapsule 0.4.0 Alpha

## 发布文件

- `LabCapsule-0.4.0.apk` — Android 8.0+ 中文控制器，82,330 字节。
- `LabCapsule-0.4.0-ota.bin` — ESP32-S3 应用 OTA 镜像，1,326,320 字节。

## SHA-256

```text
85103E73A58631AF09A1C6BAAD94D386354136EE075F0B2702C9573A91EB0535  LabCapsule-0.4.0.apk
0B938988698A116CD2920C65D709FA3927383DB2C75B3F2013FD6BFFF73DE855  LabCapsule-0.4.0-ota.bin
```

## 安装说明

从 0.1.x 或旧分区表升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 bootloader、OTA data 和新分区表。完成首次完整烧录后，后续版本可以在 APK 中使用 Wi-Fi 或 BLE OTA bin。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.4.0 把 APK 主导航重构为“首页 / 实验 / 数据 / AI / 设置”，增加快捷实验、自定义协议、实验记录和真实 CSV RMS/Peak/FFT 分析。设备、屏幕/GIF、固件维护统一进入默认折叠设置。GIF 改为手机端一次性缓存、Android 前台服务后台播放，并新增经 BLE 实机验证的 `delta332` 稀疏差分协议。
