# LabCapsule 项目结构与维护约定

## 源码目录

| 目录 | 内容 | 可提交内容 |
|---|---|---|
| `android/` | 原生 Android 客户端、资源和无 Gradle 构建脚本 | Java、Manifest、资源、构建脚本 |
| `desktop/` | Windows Studio、Live2D 运行时、电脑桥和数据工具 | Python、Web 源码、锁文件、必要的打包资源 |
| `firmware/` | ESP-IDF 固件、分区表和默认配置 | C、头文件、CMake、默认 `sdkconfig` |
| `knowledge/` | 可按需读取的硬件/传感器知识库 | 脱敏 Markdown 与目录索引 |
| `shared/` | 设备身份、记忆和角色卡 Schema | 版本化 JSON Schema |
| `skills/` | 桌宠创建与上下文读取 Skill | 指令、脚本、参考资料，不含用户模型 |
| `tests/` | 自动化测试和显式命名的手工硬件测试 | 合成数据、无凭据测试代码 |
| `docs/` | 当前指南、版本记录和实测报告 | 脱敏文档，不含个人路径/真实硬件身份 |
| `release/` | 发布入口说明 | 仅 `README.md`，二进制放 GitHub Releases |

`analysis/`、`experiment_engine/`、`experiments/`、`hardware/` 和 `mechanical/` 保留为后续扩展边界；空目录用 `.gitkeep` 维护。

## 不进入仓库的内容

- `build/`、`dist/`、`firmware/build/`、Android 构建输出和 PyInstaller 临时目录；
- APK、EXE、BIN、ELF、签名仓库、证书和私钥；
- `.env*`、`secrets.json`、`credentials.*` 和本地配置；
- Live2D/VRM/语音包等第三方或用户资源；
- 原始实验 CSV、处理后数据、图表和现场照片；
- IDE 配置、缓存、日志及机器专属路径。

## 发布流程

1. 更新版本号、发布说明和测试报告。
2. 运行 `tools/security_audit.ps1` 与完整单元测试。
3. 分别构建固件、APK 和 Windows EXE，并记录 SHA-256。
4. 提交并推送纯源码；标签必须指向已验证的提交。
5. 将三个二进制作为 GitHub Release 资产上传，不把它们提交到 Git 历史。
6. 商业发布前使用正式 Android/Windows 签名，并在干净环境复验安装与升级。

## 隐私示例规则

文档和测试使用 `lc-000000000000`、`live2d-000000000000`、`<仓库目录>`、`<Live2D 模型目录>` 等合成值。实机报告可以记录芯片型号、内存规格、采样率和样本数，但不得记录 MAC、真实设备 ID、个人目录或私有仓库地址。
