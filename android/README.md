# LabCapsule Android Remote 1.0.0

原生 Java Android 8.0+ 控制器，不依赖 Gradle 或第三方 Android 运行库。默认简体中文，采用“首页 / 实验 / 数据 / AI / 设置”五分区液态导航；设备、屏幕、网络、记忆和固件位于默认折叠的设置区。

完整用户步骤见 [V1.0 统一随身实验助手指南](../docs/V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md)。

## V1 能力

- BLE 与局域网 HTTP 双通道；BLE 不切换手机 Wi-Fi，可完成配网、I²C 扫描、控制、实验、离线同步、媒体和 OTA。
- 状态卡明确显示稳定 `deviceId`、`characterId`、`staConnected` 和 `staIp`。ESP32-S3 仅支持 2.4 GHz，纯 5 GHz 下可继续使用 BLE。
- Hiyori 对话、Android 系统语音输入、OpenAI 兼容 AI 和 Experiment Protocol 本地回退。
- 选择完整 Live2D 文件夹后递归复制到应用私有目录；校验 `model3.json`，按内容生成跨端一致 ID。模型不会上传仓库或打入 APK。
- AI 的白名单情绪/动作同步到手机 Live2D、实体 Hiyori 动作和屏幕底部 216×64 气泡。
- 用户自己的私有 GitHub 仓库按稳定设备 ID 同步事实与实验摘要；Token 由 Android Keystore 加密，公开仓库拒绝写入。
- 在线 BLE 六轴数据保存到应用私有 CSV；无人接收时设备写离线分区，之后可同步并执行 RMS、Peak、FFT 与主频分析。
- JPG/PNG/WebP/GIF 在手机端先裁剪、缩放、黑/白补底、抽帧和差分压缩。设备只保存当前壁纸或当前动画，退出 APK 后继续播放。
- 1–8 FPS 真实帧率、25%–800% 裁剪缩放、240×320 同比例状态监看、多层透明度和三套界面预设。
- 从 GitHub Releases 检查 APK 和 OTA 更新；系统仍会要求用户确认 APK 安装。

## 构建

需要 Android SDK Platform 35、Build Tools、Java 编译器以及 D8。运行：

```powershell
cd <仓库目录>\android
.\build-apk.ps1
```

输出 `dist\LabCapsule-1.0.0.apk`。脚本执行 aapt2、javac、D8、zipalign 和 apksigner。仓库里的 keystore 仅用于开发测试；商业发布必须更换正式私钥。

## 推荐连接流程

1. 手机保持连接正常、有互联网的 Wi-Fi。
2. “设置 → 设备与连接 → 扫描 BLE”，连接 `LabCapsule-XXXX`。
3. 需要局域网时使用“蓝牙一键配网”，输入真实 2.4 GHz SSID/密码；手机本身不会换网。
4. 等状态卡出现 `staConnected=true` 和非 `0.0.0.0` 的 `staIp`，再切换为局域网通道。
5. 只有 5 GHz 时保留 BLE，不要让手机长期连接恢复热点。

恢复热点 `LabCapsule-XXXX` / `labcapsule` / `http://192.168.4.1` 只作为排障后备。

## 导入 Hiyori

1. 把完整 `hiyori_free` 文件夹复制到手机。
2. 进入“AI → 选择现有 Live2D 文件夹”。
3. 阅读并确认模型与 Cubism SDK 条款，然后选择整个文件夹。
4. 等待“已保存到 APK 私有目录”；重新进入 AI 页应显示 Live2D 舞台。
5. 连接设备后发送对话，动作会同步到手机和实体屏。

限制为 800 文件、128 MiB 和 12 层目录。导入使用 `current.tmp → current` 原子切换；失败不会覆盖旧角色。

## 私有记忆

在“设置 → AI 与私有记忆”填写私有仓库 `owner/repo`、分支和只授予该仓库 Contents 读写的细粒度 Token，再启用同步。路径固定为 `memory/devices/<deviceId>/snapshot.json`。API Key、Token、密码、Wi-Fi 凭据和原始音频不会写入记忆。

## 媒体策略

图片/GIF 必须先在 3:4 编辑器确认裁剪。GIF 会一次性转成设备本地 LCG；基准帧和后续帧分别自动选择 RGB332/RLE332/`delta332` 的较小编码。速度使用 1–8 FPS，不使用百分比。替换媒体时只保留当前图片或 GIF。

ST7789 为只写 SPI，所以 APK 的 240×320 监看是根据设备页面、实验、传感器、背光和 HUD 状态进行同构渲染，不是假装读取面板像素。

## 安全边界

- Wi-Fi/MQTT/API/GitHub 密钥使用 Android Keystore AES-GCM。
- AI 无权直接更新固件、改网络、清空数据或跳过用户确认启动实验。
- 局域网 HTTP 面向受信任网络，当前没有逐设备登录。
- Live2D 模型和用户记忆不会进入 LabCapsule 公共仓库。
