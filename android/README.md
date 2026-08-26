# LabCapsule Android Remote 0.3.1

原生 Java Android 8.0+ 控制器，不依赖 Gradle 或第三方运行库。界面默认中文，采用五分区透明液态滚轮导航：设备、屏幕、实验、AI、设置。

## 功能

- 局域网 HTTP 与 Bluetooth LE 两种设备通道；传输选择在设备、屏幕和固件区保持同步。
- 屏幕主页/设置/开发诊断/彩条/壁纸/反色/背光/方向键/确认/中止遥控。
- JPG、PNG、WebP 和 GIF 必须先在触控编辑器中拖动/缩放并确认 3:4 裁剪，原始大文件不发送给设备。
- 静态图片在手机端缩放并选择 RGB565/RLE565；GIF 在手机端使用 RGB332、变化矩形和 RLE，未变化帧跳过。
- 图片可经 Wi-Fi 或 BLE 显示；壁纸写入专用分区，GIF 的原文件、时间轴、解码与压缩都留在手机。
- 传感器扫描和状态查询；Wi-Fi/BLE 双通道 OTA。
- 外部 Wi-Fi、恢复热点、亮度及 mqtt/mqtts 远程参数配置；设备页直接显示“未配置 / 连接中或失败 / 已连接”和可点击使用的局域网 IP。
- OpenAI 兼容 AI 配置，默认 DeepSeek；协议字段和设备安全范围校验，AI 失败时本地回退。
- 启动时检查 GitHub Releases；可下载 APK 和 OTA bin。

敏感字段通过 Android Keystore AES/GCM 加密。API Key 不发送给 ESP32。

## 构建

需要本机 Android SDK Build Tools。运行：

```powershell
cd <仓库目录>\android
.\build-apk.ps1
```

输出：`dist/LabCapsule-0.3.1.apk`。脚本会完成资源编译、Java 编译、DEX、APK 对齐、签名及签名验证。开发签名文件位于本机并被 `.gitignore` 排除。

## 初次连接

### 恢复热点

1. 手机连接 `LabCapsule-XXXX`，密码 `labcapsule`。
2. APK 的设备地址使用 `http://192.168.4.1`。
3. 在设置中配置外部 2.4 GHz Wi-Fi，返回设备页等待“外部 Wi-Fi 状态”显示已连接。
4. 看到 `局域网 IP：http://...` 后点击“使用此局域网 IP”，再让手机切回原有互联网 Wi-Fi。

若只显示“已保存配置，正在连接或连接失败”，表示固件中的 `staConfigured=true`、`staConnected=false`；请检查 2.4 GHz、SSID 和密码。APK 已把原始 JSON 状态翻译为明确中文，无需手工查找字段。

### BLE

点击“扫描并连接 BLE”，允许 Android 12+ 的附近设备权限。BLE 适用于控制、状态、图片、壁纸和 OTA。GIF 会自动降低逻辑帧率并采用压缩变化区域；大量或高帧率媒体仍优先使用局域网。

## 图片与 GIF

1. 在“屏幕”点击“选择并裁剪”，选取 JPG、PNG、WebP 或 GIF。
2. 在白色 3:4 框内拖动图片，双指缩放；点击“确认裁剪”后才能发送。
3. “显示图片”保留 RGB565 色彩并自动尝试 RLE565；“保存壁纸”固定使用完整 RGB565 写入持久分区。
4. “播放 GIF”使用手机端 RGB332 量化、帧差矩形和 RLE332。Wi-Fi 目标约 8 fps，BLE 约 2.8 fps，实际速度受图案复杂度和链路影响。
5. 媒体说明会实时显示编码、区域尺寸、字节数和相对旧版整帧的节省比例。

## AI 协议

接受的 JSON 至少包含：

```json
{
  "name": "不同材料振动衰减",
  "sample_rate_hz": 200,
  "duration_seconds": 20,
  "groups": ["对照组", "泡棉组"],
  "analysis": ["RMS", "Peak", "FFT"]
}
```

采样率允许 10–500 Hz，时长允许 1–3600 秒。点击“发送并开始实验”后，Wi-Fi 使用 `/api/experiment`，BLE 使用 `START:<rate>:<duration>`。

## 在线更新限制

应用使用 GitHub Releases API 查找 `.apk` 和文件名含 `ota` 的 `.bin`。固件可在应用内更新；APK 下载完成后由 Android 系统安装器显示确认，普通应用不能静默替换自身。
