# LabCapsule Studio 1.0.0

Windows 可视化实验与 Hiyori 助手，支持 USB、局域网 HTTP 和 Bluetooth LE。应用不会切换电脑 Wi-Fi，也不会主动加入设备的无网络恢复热点。

完整操作见 [V1.0 统一随身实验助手指南](../docs/V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md)，验收证据见 [V1.0 测试报告](../docs/V1.0.0_TEST_REPORT_ZH.md)。

## 主要能力

- 顶部选择 USB / 局域网 WiFi / BLE；三条链路统一显示稳定 `deviceId`、角色、STA 和传感器状态。
- 默认页面为“实验助手 / 实验数据 / 设置”；设备、屏幕工作室和诊断在设置中默认折叠。
- 连接 COM8 后读取六轴数据，自动保存每个设备的 CSV/JSON 会话；图表支持悬停坐标、双 Y 轴、滚轮缩放、拖动和平移复位。
- Hiyori Live2D 真实 WebGL 舞台、动作联动和透明悬浮层；同一模型可生成 240×320 设备本地代理，不向 ESP32 持续推帧。
- OpenAI 兼容 AI、16 kHz 麦克风转写、设备/电脑/实验上下文、安全本地回退，以及受限的本机 Claude 复杂任务转交。
- 用户私有 GitHub 仓库按稳定硬件 ID 同步脱敏记忆；GitHub/API Key 由当前 Windows 用户 DPAPI 加密。
- 图片/GIF/视频在电脑端完成裁剪、缩放、补底、抽帧和差分压缩；USB/LAN/BLE 可上传壁纸、当前动画和 AI 气泡。
- Windows 通知和 CPU/内存/磁盘摘要可显示到闲置设备；开始实验时自动切到实验界面。

## 运行源码

```powershell
cd <仓库目录>\desktop
python -m pip install -r requirements.txt
.\run.ps1
```

## 打包单文件 EXE

```powershell
cd <仓库目录>
pyinstaller --noconfirm --clean LabCapsule-Studio-1.0.0.spec
```

输出为 `dist\LabCapsule-Studio-1.0.0.exe`。商业发行前应增加 Windows 代码签名。

## 使用现有 Hiyori

选择 `<Live2D模型目录>\hiyori_free` 父文件夹即可自动发现 runtime 模型和 8 组动作。模型内容 ID 为 `live2d-000000000000`；旧版 `local-*` 选择会迁移。应用不复制或分发模型，启动时重新校验源文件。

首次运行须由用户确认适用的 Live2D/Cubism 条款。Cubism Core 从 Live2D 官方固定地址加载，模型只通过本机回环服务提供给播放器。

## 连接与实验

- USB：优先 COM8，460800 8N1，适合固件、媒体和长时间实验。
- LAN：填写设备已获得的 `http://192.168.x.x`；只访问当前网络，不替电脑换网。
- BLE：连接 `LabCapsule-XXXX`，适合只有 5 GHz Wi-Fi 时的控制、实验、状态、媒体和气泡。

曲线操作：鼠标悬停读取样本；滚轮缩放时间；`Ctrl + 滚轮`缩放 Y 轴；左键拖动；双击复位。显示抽稀不改变导出的原始 CSV。

## AI 与记忆

OpenAI 兼容 Endpoint、聊天模型、转写模型和 Key 均可配置。复杂任务自动转交 Claude 时，子进程固定为单轮只读、禁用工具/MCP/浏览器和会话持久化。

记忆仓库必须是私有仓库，Token 应为只允许该仓库 Contents 读写的细粒度 Token。同步文件为 `memory/devices/<deviceId>/snapshot.json`；不要把 Token、API Key、密码或原始音频提交仓库。
