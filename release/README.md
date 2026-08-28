# LabCapsule 0.6.0 Alpha

## 发布文件

- `LabCapsule-0.6.0.apk` — Android 8.0+ 中文控制器，98,714 字节。
- `LabCapsule-0.6.0-ota.bin` — ESP32-S3 应用 OTA 镜像，1,382,256 字节。

## SHA-256

```text
F7F0DA39F483D0868663320B53124D77825556A0C731B564FB0E7F33C949E530  LabCapsule-0.6.0.apk
D74BF2EE70CFB69721AA98E86A93030A87BC7BBADEBA79D2FD1EC371E0EAD01C  LabCapsule-0.6.0-ota.bin
```

## 安装说明

从 0.4.x 或更旧版本升级时，请先通过 USB 运行 `idf.py -p COM8 flash`，以写入 8 MiB 离线实验分区。0.5.0 可直接使用本版本 OTA bin。完成首次完整烧录后，后续同分区版本可以在 APK 中使用 Wi-Fi 或 BLE OTA。

APK 采用 v2/v3 签名。Android 会要求用户确认安装或升级；这是系统安全要求。

V0.6.0 增加闲置信息/实验直传双模式、设备硬件负载、可选手机通知镜像及隐私模式；GIF 支持 25%–300% 运行中调速，裁剪支持 100%–800% 滑杆和双指缩放。BLE 状态路径移除大 JSON 二次解析，修复模式切换时可能发生的堆损坏。V0.5.0 的统一输入、离线实验、BLE 实时数据与 APK CSV 分析继续保留。

实机基准：模式/通知/硬件往返连续 3 轮通过；Mock BLE 在线通知 200/200 且不新增缓存会话；3 组、507 个已有样本完整导出。当前 I²C `0x68` 返回异常 `WHO_AM_I=0x70`，真实采集前请确认模块。完整说明见 `docs/V0.6.0_IDLE_GIF_MODE_GUIDE_ZH.md`。
