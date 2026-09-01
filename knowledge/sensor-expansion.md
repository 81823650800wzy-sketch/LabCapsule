# 传感器扩展规则

每个驱动声明 `id/name/bus/addresses/channels/units/maxRate`，实现探测、初始化、采样和健康状态。扫描只报告实际发现的地址；AI 回答时加载命中的元件条目、当前设备能力和本次扫描结果，不把整个硬件手册塞入上下文。

新增传感器时同时更新固件驱动注册、`knowledge/catalog.json`、协议字段和一项 Mock/实机测试。
