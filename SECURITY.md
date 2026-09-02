# LabCapsule 安全策略

## 凭据边界

仓库不得包含 API Key、GitHub Token、Wi-Fi/MQTT 密码、私钥、签名仓库、真实设备 MAC、稳定设备 ID、个人邮箱或本机绝对路径。

- Android 的 API Key、同步 Token、配对 Token 和网络密码由 Android Keystore 保护的本地存储保存。
- Windows 的 API Key、同步 Token和语音服务密钥由当前用户的 DPAPI 本地保护。
- ESP32 的 Wi-Fi/MQTT 配置保存在设备 NVS；量产设备还应启用 Secure Boot、Flash Encryption 和加密 NVS。
- Live2D 模型、语音包、记忆库和实验原始数据默认属于用户资产，不进入本仓库。
- GitHub 同步应使用私有仓库和最小权限、可撤销的细粒度 Token。

示例、测试和文档只能使用合成标识，例如 `lc-000000000000`。发布前运行：

```powershell
pwsh -File tools/security_audit.ps1
python -m unittest discover -s tests -p "test_*.py"
```

## 网络边界

- 恢复热点与局域网 HTTP 只适用于受信任网络；跨网络访问应使用 MQTT over TLS 或受控的电脑桥。
- 电脑桥默认关闭，使用短时配对码和独立 Bearer Token，并按权限范围授权。
- Claude 联网参考只开放有界的网页搜索/读取，不开放 Shell、文件写入或隐式设备控制。
- Android 通知、麦克风、附近设备和文件访问均由系统权限控制，可单独撤销。

## 泄露处理

如果凭据曾被提交，应立即在对应服务撤销/轮换；删除当前文件并不能使旧提交中的凭据失效。随后清理 Git 历史、强制更新受影响分支与标签，并通知所有克隆者重新克隆或重置。

请通过仓库的 [GitHub Security Advisories](https://github.com/81823650800wzy-sketch/LabCapsule/security/advisories/new) 私下报告安全问题，不要在公开 Issue 中粘贴凭据或个人数据。

## 发布签名

开发构建可以使用本机开发签名，但公开商业发布必须使用独立保管的 Android 正式签名密钥和 Windows Authenticode 证书。签名密钥与证书文件永不进入仓库。
