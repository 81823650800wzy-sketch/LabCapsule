# LabCapsule 1.2.0 Alpha（角色卡与手机电脑协同）

## 发布文件

- `LabCapsule-1.2.0.apk` — Android 8.0+ 简体中文客户端，393,781 字节。
- `LabCapsule-Studio-1.2.0.exe` — Windows 10/11 x64 单文件 Studio，85,875,274 字节。
- ESP32-S3 固件协议没有改变，继续使用 V1.0.0-alpha / 0.11 系列兼容固件；本版不要求重新烧录。

## SHA-256

```text
7E603AF0CB5FF871461567AC697D29288A85B1605C07C0EFE5FDB6890715F1C7  LabCapsule-1.2.0.apk
30BB5F104A8BBF2F5A5175009CF685882C786F646C413CAA7C1857C6B973B653  LabCapsule-Studio-1.2.0.exe
```

## 安装顺序

1. 保持电脑和手机连接原有正常联网 Wi-Fi，不连接 LabCapsule 无网络恢复热点。
2. Windows 运行 `LabCapsule-Studio-1.2.0.exe`；Android 安装 `LabCapsule-1.2.0.apk`。
3. 设备仍优先使用 USB COM8；只有 5 GHz 路由器时，ESP32 使用 USB/BLE，手机和电脑保持自身网络。
4. 需要手机访问电脑时，由用户在 Studio 设置中手动开启手机桥，再在 APK 输入一次性配对码。
5. 需要双端角色卡时，在两端填写同一个私有 GitHub 仓库、分支和具有 Contents/Releases 权限的细粒度 Token。

完整步骤：[V1.2 使用指南](../docs/V1.2.0_ROLECARD_COLLAB_GUIDE_ZH.md)
验证证据：[V1.2 测试报告](../docs/V1.2.0_TEST_REPORT_ZH.md)
