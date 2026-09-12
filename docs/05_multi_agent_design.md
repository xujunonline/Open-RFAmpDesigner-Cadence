# 多智能体设计

第一版 agent 使用确定性 Python 类模拟调度，后续再接入 LLM。

- Manager：维护候选队列，选择 search 或 refine。
- Searcher：生成资源分配和关键级候选。
- Refiner：根据 violation 回溯 Stage 2/3/1。
- Memory：保存 KB/EB JSONL。

所有 agent 输出都必须可以序列化为 JSON，便于复现实验和审计。

