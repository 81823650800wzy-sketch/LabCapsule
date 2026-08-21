# LabCapsule

> **Ask a question. Run an experiment.**

**LabCapsule** 是一个低成本、便携、模块化的 AI 辅助实验平台，让用户从"提出一个现实世界的问题"开始，而不是从"学习如何使用仪器"开始。

当前阶段：**V0.1 Alpha**（2026-08-21 → 2026-09-02，预算 ¥200）

完整规格见 [SPEC_V0.1.md](./SPEC_V0.1.md)。

---

## 一句话

能否把**自然语言**变成物理实验的入口？

```text
自然语言问题 → 实验方案 → 物理数据采集 → 自动分析 → 实验结果
```

---

## 核心闭环

```text
Natural Language Question
          ↓
Experiment Generator
          ↓
Experiment Protocol
          ↓
LabCapsule Device  (ESP32-S3 + MPU6050)
          ↓
Data Acquisition
          ↓
Data Analysis      (RMS / Peak / FFT)
          ↓
Experiment Result
```

---

## V0.1 硬件

| 模块 | 型号 | 状态 |
|------|------|------|
| 主控 | ESP32-S3 开发板（N8/N16, R8, USB-C） | 已采购 |
| 传感器 | MPU6050（I²C） | 已采购 |
| 显示 | 2.4" TFT ST7789 240×320 SPI | 已采购 |
| 输入 | 摇杆 + Back/Abort 按键 | 已有 |
| 电源 | USB-C | — |

> 硬件引脚（GPIO / Pinout）均为 **TBD**，到货实测后再冻结。

---

## 目录结构

```text
LabCapsule/
├── firmware/            ESP32-S3 固件
├── desktop/             PC 端图形界面
├── experiment_engine/   实验引擎（状态机）
├── analysis/            数据分析（RMS / Peak / FFT）
├── hardware/
│   ├── schematic/
│   ├── pcb/
│   └── datasheets/
├── mechanical/
│   ├── cad/
│   └── stl/
├── experiments/         实验数据
├── tests/
├── docs/
│   └── devlog/          每日开发日志
├── SPEC_V0.1.md
└── README.md
```

---

## Experiment Protocol（核心接口）

```json
{
  "name": "Vibration Isolation Test",
  "sensor": "motion",
  "sample_rate": 200,
  "duration": 10,
  "groups": ["no_padding", "foam", "rubber"],
  "analysis": ["rms", "peak", "fft"]
}
```

AI（DeepSeek）只负责 `自然语言 → Experiment Protocol JSON`，**不允许直接控制硬件**。

---

## 开发日志

见 [docs/devlog/](./docs/devlog/)。

---

## License

TBD
