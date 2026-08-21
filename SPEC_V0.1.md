# LabCapsule V0.1 Alpha

> **项目阶段：** V0.1 Alpha
> **启动日期：** 2026-08-21
> **阶段结项日期：** 2026-09-02
> **预算上限：** ¥200
> **项目性质：** 个人科研工具 / 开放硬件 / AI 实验辅助平台
> **核心目标：** 在低成本硬件上验证"自然语言问题 → 实验方案 → 物理数据采集 → 自动分析 → 实验结果"的完整闭环。

---

# 1. 项目一句话定义

**LabCapsule 是一个低成本、便携、模块化的 AI 辅助实验平台，让用户从"提出一个现实世界的问题"开始，而不是从"学习如何使用仪器"开始。**

核心理念：

> **Ask a question. Run an experiment.**

目标不是制造另一台万用表、示波器或普通数据记录仪，而是探索：

> **能否把自然语言变成物理实验的入口。**

---

# 2. 项目背景

传统物理实验或电子实验通常要求用户提前掌握：

* 应该选择什么传感器；
* 如何连接传感器；
* 应该使用多高的采样率；
* 应该采集多久；
* 如何设置实验组和对照组；
* 如何保存实验数据；
* 如何进行数据处理；
* 如何使用 RMS、FFT 等分析方法；
* 如何根据数据得到结论。

LabCapsule 希望降低这部分门槛。

例如用户提出：

> 我想研究不同材料垫在桌子下面，哪一种减震效果最好。

系统将这个问题转换为：

```text
实验名称：
Vibration Isolation Test

传感器：
Motion Capsule

实验组：
1. 无垫片
2. 泡沫
3. 橡胶

采样：
200 Hz

每组时间：
10 s

分析：
RMS
Peak
FFT
```

设备随后引导用户逐组完成实验，并自动生成实验结果。

---

# 3. V0.1 核心目标

V0.1 不追求成为完整科研仪器。

本阶段只验证一个核心闭环：

```text
Natural Language Question
          ↓
Experiment Generator
          ↓
Experiment Protocol
          ↓
LabCapsule Device
          ↓
Motion Sensor
          ↓
Data Acquisition
          ↓
Data Analysis
          ↓
Experiment Result
```

最终必须能够完成：

```text
用户提出问题
      ↓
生成实验方案
      ↓
设备显示实验步骤
      ↓
用户完成多组测量
      ↓
ESP32-S3采集真实数据
      ↓
PC端保存数据
      ↓
RMS / Peak / FFT
      ↓
比较实验组
      ↓
输出结果
```

---

# 4. V0.1 功能范围

## 4.1 必须实现 P0

以下功能不可删除：

* ESP32-S3 正常运行；
* MPU6050 加速度/陀螺仪数据采集；
* ESP32-S3 → PC 数据传输；
* 原始数据保存为 CSV；
* 多组对照实验；
* RMS 分析；
* Peak 分析；
* FFT 分析；
* 实验组比较；
* 最终实验结果页面；
* 至少 3 个真实实验。

只要 P0 完成，LabCapsule V0.1 即认为核心概念验证成功。

---

## 4.2 产品化功能 P1

尽量完成：

* ST7789 设备屏幕；
* 摇杆操作；
* Back / Abort 独立按键；
* 实验状态显示；
* 3D 打印外壳；
* Carrier PCB；
* Motion Capsule PCB；
* PC 图形界面。

---

## 4.3 创新功能 P2

时间允许后实现：

* DeepSeek 自然语言实验生成；
* Experiment Protocol；
* AI 输出 Schema Validation；
* Motion Capsule 自动识别概念；
* 自描述传感器接口雏形；
* Capsule 模块化结构。

---

# 5. 明确禁止进入 V0.1 的功能

以下全部进入 V0.2 Roadmap：

* 麦克风；
* GPS；
* NFC；
* CO₂；
* 光照传感器；
* 温湿度传感器；
* 手机 App；
* 云同步；
* 用户账户；
* 语音控制；
* 多 AI Agent；
* 高速示波器；
* 专业级数据采集；
* 锂电池完整供电系统；
* 大量 Sensor Capsule；
* 复杂机器学习；
* 自动控制现实设备。

2026-08-30 后禁止新增任何功能。

---

# 6. 当前硬件

## 6.1 主控

ESP32-S3 开发板。

配置：

```text
ESP32-S3
Flash：N8/N16
PSRAM：R8
USB-C
```

具体开发板尺寸、排针和 GPIO：

```text
TBD — 到货后实测
```

V0.1 不自行集成 ESP32-S3 裸芯片/模组。

最终 Carrier PCB 继续使用该开发板。

---

# 7. Motion Sensor

使用：

**MPU6050 模块**

通信：

```text
I²C
```

主要数据：

```text
AX
AY
AZ

GX
GY
GZ
```

V0.1 主要利用加速度数据研究：

* 振动；
* 运动；
* 周期；
* 冲击；
* 简单姿态变化。

---

# 8. 显示系统

使用：

```text
2.4" TFT
ST7789
240 × 320
SPI
8 Pin Blue PCB
```

具体 Pinout：

```text
TBD — 到货后根据实物确认
```

禁止在确认实物之前让 AI 自行猜测引脚。

屏幕主要负责：

* Boot；
* Home；
* Experiment Ready；
* Recording；
* Next Group；
* Result；
* Error。

复杂 FFT 图表和实验报告主要由 PC 端显示。

---

# 9. 输入系统

原 EC11 编码器方案取消。

V0.1 改为已有摇杆。

预计接口：

```text
VCC
GND
VRX
VRY
SW
```

具体型号：

```text
TBD — 实物确认
```

操作逻辑：

```text
UP       菜单向上
DOWN     菜单向下
LEFT     返回/上一项
RIGHT    下一项
PRESS    确认
```

额外保留一个独立两脚按键：

```text
BACK / ABORT
```

主要用于：

* 返回；
* 中止采集；
* 紧急退出当前实验。

---

# 10. 电源

V0.1：

```text
USB-C
↓
ESP32-S3 Development Board
↓
3.3V
↓
Sensors / Logic
```

暂时不加入锂电池。

原因：

* 减少调试变量；
* 避免充电管理；
* 避免保护电路；
* 避免电源切换；
* 降低 PCB 风险；
* 节省开发时间。

V0.2 再加入真正便携电池系统。

---

# 11. V0.1 PCB 架构

V0.1 不直接设计高度集成主板。

采用：

## Core Carrier Board

```text
┌─────────────────────────────┐
│ LAB CAPSULE CORE V0.1       │
│                             │
│ ESP32-S3 Development Board  │
│                             │
│ Display Interface           │
│                             │
│ Joystick Interface          │
│                             │
│ Back / Abort                │
│                             │
│ Capsule Interface           │
│                             │
│ Test Points                 │
└─────────────────────────────┘
```

ESP32-S3 开发板通过排针/母座安装。

目的：

* 开发板可拆；
* 容易调试；
* 容易飞线；
* PCB 出错不导致 ESP32 报废；
* V0.1 风险较低。

---

# 12. Motion Capsule

第一块 Capsule：

```text
MOTION CAPSULE V0.1
```

使用现有 MPU6050 模块。

结构：

```text
┌───────────────────┐
│ MOTION CAPSULE    │
│                   │
│ MPU6050 Module    │
│                   │
│ Optional ID       │
│                   │
└─────────┬─────────┘
          │
     Capsule Port
```

第一版可以使用 MPU6050 模块，而不是直接焊 MPU6050 芯片。

V0.2 再集成传感器 IC。

---

# 13. Capsule Interface

预计至少包括：

```text
3V3
GND
SDA
SCL
INT
ID / RESERVED
```

最终 Pinout：

```text
TBD — 2026-08-26 GPIO Freeze
```

未来目标：

传感器模块能够描述：

```text
TYPE
UNIT
RANGE
SAMPLE RATE
CAPABILITIES
```

例如：

```text
TYPE:
accelerometer

CAPABILITIES:
vibration
motion
tilt
frequency_analysis
```

V0.1 只做概念基础，不要求完整实现。

---

# 14. 软件总体架构

建议目录：

```text
LabCapsule/
│
├── firmware/
│
├── desktop/
│
├── experiment_engine/
│
├── analysis/
│
├── hardware/
│   ├── schematic/
│   ├── pcb/
│   └── datasheets/
│
├── mechanical/
│   ├── cad/
│   └── stl/
│
├── experiments/
│
├── tests/
│
├── docs/
│   └── devlog/
│
├── SPEC_V0.1.md
│
└── README.md
```

---

# 15. SensorSource 抽象

软件必须支持两种数据源：

```text
SensorSource
│
├── MockSensor
│
└── SerialSensor
```

MockSensor：

用于硬件未到货、硬件故障、软件测试和 Demo fallback。

SerialSensor：

用于真实 ESP32-S3。

原则：

> 上层 Experiment Engine 不应该关心数据来自 Mock 还是真实设备。

---

# 16. Experiment Protocol

Experiment Protocol 是 LabCapsule 的核心软件接口。

示例：

```json
{
  "name": "Vibration Isolation Test",
  "sensor": "motion",
  "sample_rate": 200,
  "duration": 10,
  "groups": [
    "no_padding",
    "foam",
    "rubber"
  ],
  "analysis": [
    "rms",
    "peak",
    "fft"
  ]
}
```

未来 AI 的主要任务：

```text
Natural Language
        ↓
Experiment Protocol JSON
```

AI 不允许直接控制硬件。

---

# 17. Experiment Engine

状态机：

```text
CREATE
↓
PLAN
↓
READY
↓
RECORDING
↓
PROCESSING
↓
NEXT_GROUP
↓
RECORDING
↓
...
↓
COMPLETE
```

异常状态：

```text
ERROR
ABORTED
DEVICE_DISCONNECTED
INVALID_PROTOCOL
```

---

# 18. DeepSeek 定位

DeepSeek 在 V0.1 中只承担：

> 自然语言研究问题 → Experiment Protocol

例如：

输入：

```text
我想研究不同材料哪个更减震。
```

输出：

```json
{
  "name": "Material Vibration Comparison",
  "sensor": "motion",
  "sample_rate": 200,
  "duration": 10,
  "groups": [
    "baseline",
    "material_a",
    "material_b",
    "material_c"
  ],
  "analysis": [
    "rms",
    "fft"
  ]
}
```

必须经过：

```text
AI
↓
JSON
↓
Schema Validation
↓
Experiment Engine
```

禁止：

```text
AI
↓
直接操作GPIO
```

---

# 19. AI Fallback

必须内置至少三个实验模板：

## Template 01

Vibration Comparison

## Template 02

Fan Speed Vibration

## Template 03

Pendulum / Periodic Motion

DeepSeek/API/网络完全失败时，LabCapsule 仍然能够完整演示。

---

# 20. 数据结构

每个实验建立独立目录：

```text
experiments/
└── YYYY-MM-DD_experiment-name/
    ├── experiment.json
    ├── raw.csv
    ├── processed.csv
    ├── result.json
    ├── chart.png
    └── photo.jpg
```

CSV 至少包括：

```text
timestamp
ax
ay
az
gx
gy
gz
```

---

# 21. V0.1 数据分析

必须：

## RMS

用于比较整体振动强度。

## Peak

用于检测最大冲击/最大振动。

## FFT

用于分析主要频率成分。

输出至少包括：

```text
RMS
Peak Acceleration
Peak Frequency
```

暂时不加入复杂机器学习。

---

# 22. PC 端界面

核心流程：

```text
HOME
↓
QUESTION
↓
EXPERIMENT PLAN
↓
READY
↓
RECORDING
↓
GROUP RESULT
↓
NEXT GROUP
↓
FINAL RESULT
```

结果页至少显示：

```text
RMS Comparison

None     ██████████
Foam     ██████
Rubber   ███

Best:
Rubber

Reduction:
XX %
```

并提供：

* 时间域曲线；
* FFT；
* 原始数据；
* 实验结果。

---

# 23. ESP32 通信

开发初期优先使用简单文本协议。

示例：

```text
DATA,12345,0.01,0.02,1.01,0.30,0.10,0.20
```

字段：

```text
TYPE
TIMESTAMP
AX
AY
AZ
GX
GY
GZ
```

V0.1 不需要复杂二进制协议。

原则：

> 先稳定，再优化。

---

# 24. 3D 外壳目标

预计尺寸：

```text
约 90 × 55 × 20~30 mm
```

最终尺寸以实物测量为准。

设计：

```text
┌─────────────────────┐
│ LAB CAPSULE          │
│                     │
│      2.4" TFT       │
│                     │
│               ● JOY │
│                     │
│   BACK              │
└──────────┬──────────┘
           │
       CAPSULE
```

结构：

* 上壳；
* 下壳；
* PCB 安装柱；
* TFT窗口；
* 摇杆孔；
* USB-C开口；
* Capsule接口；
* 螺丝固定。

可选：

* 磁铁槽；
* 挂绳孔；
* 桌面支架。

---

# 25. 3D 外壳迭代

## V0

2026-08-24 前后。

只验证空间布局。

## V0.1

2026-08-25。

第一版完整 CAD。

## V0.1 Print

2026-08-26。

第一次实体打印。

目标：

发现尺寸问题。

## V0.2

2026-08-27～29。

根据实物修改。

## V0.3 Final

约 2026-08-30。

最终展示外壳。

之后只允许小修改。

---

# 26. PCB 时间表

## 2026-08-21

建立硬件文档。

不冻结 GPIO。

## 2026-08-23～24

ESP32、MPU6050验证后开始原理图。

## 2026-08-25

Carrier Board 原理图。

Motion Capsule 原理图。

## 2026-08-26

所有硬件面包板验证。

创建：

```text
PINMAP_V0.1.md
```

执行：

> GPIO FREEZE

## 2026-08-27

PCB Layout。

## 2026-08-28

完成：

* ERC；
* DRC；
* 封装检查；
* Pin1检查；
* 板框检查；
* 安装孔检查；
* 3D Viewer；
* Gerber；
* BOM。

然后：

> PCB V0.1 FREEZE

当天提交嘉立创。

---

# 27. 面包板阶段

2026-08-21～27 为主要硬件验证期。

顺序必须：

```text
ESP32
↓
ESP32 + MPU6050
↓
ESP32 + MPU6050 + TFT
↓
ESP32 + MPU6050 + TFT + Joystick
↓
ESP32 + MPU6050 + TFT + Joystick + Button
↓
完整系统
```

禁止一次性全部连接。

每加入一个模块：

1. 接线；
2. 编译；
3. 烧录；
4. 独立测试；
5. 连续运行；
6. Commit；
7. 再加入下一个模块。

---

# 28. PCB 焊接策略

PCB 到货后禁止一次全部焊接。

顺序：

```text
空板检查
↓
ESP32排针
↓
ESP32启动测试
↓
Joystick
↓
Display
↓
Capsule Connector
↓
Motion Capsule
↓
完整测试
↓
装壳
```

每一步都必须验证后再继续。

---

# 29. 2026-08-21～09-02 总计划

## 08-21

采购完成。

冻结 V0.1 功能。

建立项目工程。

Codex 恢复额度后创建 Mock 软件。

## 08-22

完成 Mock Sensor。

完成 Experiment Protocol。

假数据跑完整实验。

## 08-23

ESP32-S3 烧录。

PC串口通信。

开始 Carrier 原理图框架。

## 08-24

MPU6050真实采集。

CSV。

桌面敲击实验。

开始外壳空间模型。

## 08-25

RMS / Peak / FFT。

第一个真实对照实验。

Carrier/Motion Capsule原理图。

外壳 V0.1。

## 08-26

ST7789。

Joystick。

Button。

第一次外壳打印。

GPIO FREEZE。

## 08-27

DeepSeek Experiment Protocol。

PCB Layout。

外壳 V0.2。

## 08-28

PCB ERC/DRC。

Gerber。

PCB V0.1 FREEZE。

嘉立创下单。

停止修改硬件功能。

## 08-29

第二版外壳打印。

软件稳定性。

UI优化。

## 08-30

完整系统联调。

禁止新增功能。

完整实验至少连续运行 5 次。

## 08-31

真实实验日。

完成至少三个实验。

## 09-01

Demo 视频。

GitHub README。

架构图。

实验结果。

产品照片。

## 09-02

最终验收。

创建：

```text
v0.1-alpha
```

Release。

备份。

暂时结项。

---

# 30. 三个 V0.1 Demo

## Demo A — Material Vibration

问题：

> 哪种材料减震效果最好？

比较：

```text
None
Foam
Rubber
Other
```

输出：

RMS + FFT。

---

## Demo B — Fan Vibration

问题：

> 风扇不同档位的振动有什么区别？

比较：

```text
OFF
Level 1
Level 2
Level 3
```

输出：

振动 RMS + Peak Frequency。

---

## Demo C — Motion / Pendulum

问题：

> 这个摆的运动周期是多少？

使用：

加速度/陀螺仪。

输出：

周期和主要频率。

如果实现困难，可替换为：

> 桌面不同位置的振动差异。

---

# 31. 项目成功标准

V0.1 成功不等于所有规划全部完成。

最低成功标准：

```text
真实IMU
+
ESP32
+
真实采集
+
多组实验
+
RMS/FFT
+
结果
```

完整成功标准：

```text
自然语言
↓
Experiment Protocol
↓
LabCapsule
↓
真实实验
↓
自动采集
↓
自动分析
↓
结果
```

---

# 32. 降级策略

如果落后 1 天：

降低设备 UI 复杂度。

如果落后 2 天：

AI 改为实验模板 + Mock AI。

如果落后 3 天：

Motion Capsule 暂时不要求物理可拔插。

如果落后 4 天：

PCB 只要求完成设计并下单。

开发板版本继续承担最终 Demo。

永远不能删除：

```text
真实数据
实验流程
数据分析
实验结果
```

---

# 33. Codex 使用规则

Codex 负责主要程序实现。

必须遵循：

1. 不允许自行扩大需求；
2. 不允许猜测 GPIO；
3. 不允许猜测硬件 Pinout；
4. 硬件未知内容使用 TBD；
5. 每完成一个模块必须运行测试；
6. 每个稳定阶段创建 Git commit；
7. 修改前读取 SPEC_V0.1；
8. Experiment Protocol 是系统核心接口；
9. MockSensor 永远保留；
10. 不因真实硬件接入删除 Mock 模式；
11. 08-30 后只修 Bug；
12. 禁止把 API Key 提交到 Git。

---

# 34. DeepSeek 使用规则

DeepSeek 负责：

```text
Research Question
↓
Experiment Protocol
```

DeepSeek 不负责：

* GPIO；
* 硬件底层控制；
* 直接采样；
* PCB；
* 电源管理；
* 绕过 Schema 操作设备。

AI 输出必须经过验证后才能执行。

---

# 35. 本地 AI 应保存的重要项目决策

当前冻结决策：

```text
PROJECT:
LabCapsule

VERSION:
V0.1 Alpha

DEADLINE:
2026-09-02

BUDGET:
<= ¥200

MCU:
ESP32-S3

SENSOR:
MPU6050

DISPLAY:
2.4" 240x320 ST7789 SPI

INPUT:
Joystick + Back/Abort Button

POWER:
USB-C

PCB:
Carrier Board + Motion Capsule

AI:
DeepSeek

CODE:
Main implementation by Codex

CORE:
Natural Language
→ Experiment Protocol
→ Physical Experiment
→ Data
→ Analysis
→ Result
```

---

# 36. 当前采购状态

已购买：

* ESP32-S3 开发板；
* MPU6050 模块；
* ST7789 TFT；
* 面包板；
* 杜邦线；
* USB-C 数据线；
* 两脚按键。

已有：

* 摇杆。

取消：

* EC11 编码器。

暂缓：

* 电池；
* 其它传感器；
* NFC；
* 麦克风；
* GPS。

---

# 37. DevLog规则

每天创建：

```text
docs/devlog/YYYY-MM-DD.md
```

格式：

```text
# Date

## Today
今天完成什么。

## Working
目前确认正常的部分。

## Broken
目前存在的问题。

## Decisions
今天冻结或修改了什么设计。

## Hardware
今天硬件状态。

## Software
今天软件状态。

## PCB
今天PCB状态。

## Mechanical
今天3D结构状态。

## Experiment
今天实验状态。

## Tomorrow
明天第一件事情。

## Evidence
照片、视频、CSV、Commit等路径。
```

禁止只在聊天记录中保存重要工程信息。

---

# 38. 版本管理

必须保留：

```text
PCB_V0
PCB_V0.1
PCB_FINAL

CASE_V0
CASE_V0.1
CASE_V0.2
CASE_V0.3

Firmware commits
Desktop commits
Experiment data
```

禁止直接覆盖所有旧设计。

---

# 39. 9月2日预期最终状态

最终目标不是商品级设备。

而是：

> **LabCapsule V0.1 Alpha —— 一台成本低于 ¥200、拥有自己 PCB 与 3D 打印结构、可以通过运动传感器采集现实世界数据，并将实验问题转化为结构化实验流程、自动完成数据分析与结果展示的 AI 原生便携科研平台概念验证机。**

预期成熟度：

```text
产品概念        高
Demo完整度      高
软件完整度      中高
硬件成熟度      中
PCB成熟度       Alpha
科研测量精度    原型级
量产成熟度      低
扩展潜力        高
```

---

# 40. V0.2 Roadmap

V0.1 完成后再研究：

### Self-Describing Capsule

模块自动描述自己的：

```text
TYPE
UNIT
RANGE
RATE
CAPABILITY
```

### Environment Capsule

温度、湿度、气压、光照。

### Acoustic Capsule

声音/频谱。

### Power Capsule

电压、电流、功率。

### Experiment Cards

NFC/二维码加载实验。

### Battery

真正脱离 USB 工作。

### Integrated PCB

从：

```text
ESP32 Development Board
```

升级为：

```text
ESP32-S3 Module
+
USB-C
+
Power Management
+
Battery
```

### Open Ecosystem

最终形成：

```text
LabCapsule Core
+
Sensor Capsules
+
3D Printable Mounts
+
Experiment Protocol
+
Experiment Library
+
AI Experiment Engine
```

---

# 41. 项目最终愿景

LabCapsule 不应该成为：

> 一个拥有很多传感器的盒子。

真正希望验证的是：

> **未来普通人是否可以像向 AI 提问一样简单地对现实世界提出一个可测量的问题。**

传统方式：

```text
问题
↓
学习仪器
↓
选择传感器
↓
编程
↓
采集
↓
Python
↓
分析
↓
结果
```

LabCapsule：

```text
问题
↓
实验
↓
结果
```

中间复杂过程由开放硬件、Experiment Protocol、数据分析系统和 AI 协同完成。

这就是 LabCapsule 项目的核心。
