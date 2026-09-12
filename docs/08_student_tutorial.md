# 面向大二学生的实施路线

## 第一步：复用 OTA 自动化框架

把你已有 OTA 项目的 SSH 调用、OCEAN 运行、PSFASCII 解析和结果排序搬到本工程。先不要接 LLM。

## 第二步：单级 RF 放大器

建立一个最简单的共源或共源共栅 RF 放大器，端口用 50 ohm。先提取 S11/S21/power。

## 第三步：加入 noise

跑 noise 仿真，提取 NF。理解为什么第一级电流、gm 和输入匹配会影响 NF。

## 第四步：加入匹配网络

扫描 `Ls, Lg, Cmatch`。用 S11 和 NF 的加权 cost 排序。

## 第五步：多级与宽带

加入第二级、第三极和等效 MCR/RLC 网络，开始看 ripple。

## 第六步：工具中间件

把主动尺寸、阻抗匹配、带宽规划、全链路评估拆成四个 Python 工具。

## 第七步：多智能体

先用确定性 Manager/Searcher/Refiner，跑通后再让 LLM 输出 JSON 决策。

