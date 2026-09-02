# LabCapsule 发布索引

源码仓库不跟踪 APK、EXE、BIN、签名文件或构建目录。所有可安装产物统一由 [GitHub Releases](https://github.com/81823650800wzy-sketch/LabCapsule/releases) 托管，以避免扩大仓库、混淆源码版本或意外携带本地配置。

## 当前版本

- [V1.3.0 Release](https://github.com/81823650800wzy-sketch/LabCapsule/releases/tag/v1.3.0)
- Android：`LabCapsule-1.3.0.apk`
- Windows：`LabCapsule-Studio-1.3.0.exe`
- ESP32-S3：`labcapsule_firmware.bin`

文件大小与 SHA-256 见 [V1.3.0 测试报告](../docs/V1.3.0_TEST_REPORT_ZH.md)，并可与 GitHub Release 资产的 `digest` 字段交叉验证。

## 安装顺序

1. 保持电脑和手机连接原有正常联网 Wi-Fi，不连接 LabCapsule 无网络恢复热点。
2. Windows 运行 V1.3.0 Studio；Android 安装 V1.3.0 APK。
3. 设备优先使用 USB；只有纯 5 GHz 路由器时，ESP32 使用 USB/BLE，手机和电脑保持自身网络。
4. 需要手机访问电脑时，由用户在 Studio 设置中手动开启手机桥，再在 APK 输入一次性配对码。
5. 需要双端角色卡时，在两端填写同一个私有 GitHub 仓库、分支和具有 Contents/Releases 权限的细粒度 Token。

完整步骤：[V1.3 使用指南](../docs/V1.3.0_AI_EXPERIMENT_GUIDE_ZH.md)

验证证据：[V1.3 测试报告](../docs/V1.3.0_TEST_REPORT_ZH.md)
