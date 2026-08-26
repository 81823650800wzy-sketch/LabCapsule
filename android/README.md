# LabCapsule Android Remote 0.3.0

原生 Java Android 8.0+ 控制器，不依赖 Gradle 或第三方运行库。界面默认中文，采用五分区透明液态滚轮导航：设备、屏幕、实验、AI、设置。

## 功能

- 局域网 HTTP 与 Bluetooth LE 两种设备通道；传输选择在设备、屏幕和固件区保持同步。
- 屏幕主页/设置/开发诊断/彩条/壁纸/反色/背光/方向键/确认/中止遥控。
- JPG、PNG、WebP 和 GIF 选择、裁切为 240×320、RGB565 转换。
- 图片可经 Wi-Fi 或 BLE 显示；壁纸写入专用分区，GIF 由手机解码并逐帧传输，不保存到 ESP32 Flash。
- 传感器扫描和状态查询；Wi-Fi/BLE 双通道 OTA。
- 外部 Wi-Fi、恢复热点、亮度及 mqtt/mqtts 远程参数配置。
- OpenAI 兼容 AI 配置，默认 DeepSeek；协议字段和设备安全范围校验，AI 失败时本地回退。
- 启动时检查 GitHub Releases；可下载 APK 和 OTA bin。

敏感字段通过 Android Keystore AES/GCM 加密。API Key 不发送给 ESP32。

## 构建

需要本机 Android SDK Build Tools。运行：

```powershell
cd <仓库目录>\android
.\build-apk.ps1
```

输出：`dist/LabCapsule-0.3.0.apk`。脚本会完成资源编译、Java 编译、DEX、APK 对齐、签名及签名验证。开发签名文件位于本机并被 `.gitignore` 排除。

## 初次连接

### 恢复热点

1. 手机连接 `LabCapsule-XXXX`，密码 `labcapsule`。
2. APK 的设备地址使用 `http://192.168.4.1`。
3. 在设置中配置外部 Wi-Fi，等状态返回 `staConnected:true` 和 `staIp`。
4. 手机切回原有互联网 Wi-Fi，把设备地址改成该 `staIp`。

### BLE

点击“扫描并连接 BLE”，允许 Android 12+ 的附近设备权限。BLE 适用于控制、状态、图片、壁纸和 OTA；大量或高帧率媒体优先使用局域网。

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
