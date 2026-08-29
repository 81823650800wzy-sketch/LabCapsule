# LabCapsule 0.7.0 Alpha

## 发布文件

- `LabCapsule-0.7.0.apk` — Android 8.0+ 简体中文控制器，102,808 字节。
- `LabCapsule-0.7.0-ota.bin` — ESP32-S3 应用 OTA 镜像，1,390,672 字节。
- `LabCapsule-Studio-0.7.0.exe` — Windows 10/11 单文件桌面工作室，73,981,011 字节，内含 FFmpeg 视频解码组件。

## SHA-256

```text
DE818CECDECB5D42FC980102D7B3817FB226F5043BF20329F43713BBE773CB8F  LabCapsule-0.7.0.apk
D308D6C9499AAB8BA9A3C6BC9217563FAE74E635822785C9FE6942DEB3BC213E  LabCapsule-0.7.0-ota.bin
5EE40B4746BA849D909D911BD8A86762FA52C569B5833583ABF36E97949D11A6  LabCapsule-Studio-0.7.0.exe
```

## 更新与安装

1. 首次使用或从 0.4.x 以前升级时，通过 USB 执行 `idf.py -p COM8 flash`，确保 8 MiB 离线/媒体分区存在。
2. 已运行 0.5/0.6 的设备可在 APK 中通过 BLE 或 Wi-Fi 安装 `LabCapsule-0.7.0-ota.bin`。
3. APK 采用 v2/v3 签名；Android 会要求用户确认安装或升级。
4. Windows 桌面工作室无需安装 Python，连接 CH343/COM8 后即可使用；它不会更改电脑 Wi-Fi。

## 重点变化

- ST7789 默认 `INVERT=OFF`。
- GIF 速度改为 1–8 FPS，真机 4→8 FPS 帧周期由 250 ms 降至 125 ms。
- 手机/电脑一次预处理并上传；设备只保存一个当前图片或动画并自主播放，退出客户端和设备重启都不停止。
- 裁剪支持 25%–800% 缩放、平移和黑/白补底。
- Windows Studio 支持电脑硬件/通知上屏、240×320 预览、图片/GIF/视频/桌宠、屏幕遥控、实时六轴曲线和 CSV。
- USB 媒体上传具备长度、CRC32、容器校验和原子替换。

COM8 实机已验证完整烧录、USB 动画上传、CRC、本地播放、运行中调速和重启自启动。测试前的原壁纸已经备份并在验收后恢复。完整说明见 `docs/V0.7.0_LOCAL_MEDIA_DESKTOP_GUIDE_ZH.md`。
