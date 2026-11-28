# C5 中文软性条目体检

VERIFIED。两套权重经 Hugging Face 的 LFS SHA-256 验证。每套模型使用同一批 18 条中文事实，每项 6 条。先对调选项，再核对附加自评时的判断。

| 模型与后端 | 条目 | AUC | 对调翻转 | 自评翻转 | 单次耗时中位（秒） | 通过 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Intern-Decision-4B / MPS | pace_fit | 1.000 | 0 | 1 | 0.365 | 否 |
| Intern-Decision-4B / MPS | grounded_reason | 1.000 | 0 | 0 | 0.376 | 是 |
| Intern-Decision-4B / MPS | stay_fit | 1.000 | 0 | 0 | 0.349 | 是 |
| Qwen3.8-27B 4bit / MLX | pace_fit | 1.000 | 0 | 0 | 0.858 | 是 |
| Qwen3.8-27B 4bit / MLX | grounded_reason | 1.000 | 0 | 1 | 1.049 | 否 |
| Qwen3.8-27B 4bit / MLX | stay_fit | 1.000 | 0 | 0 | 0.890 | 是 |

权重版本为 Intern `38c9dafbbef52dd04bae943c0c6ac918419adfd5`，Qwen `b935172e4bb5dcd0543774a34748fb92422e3027`。
Intern 体检峰值常驻内存 1166 MiB。MLX 体检结束时常驻内存 14797 MiB。通义输出温度为 0.5。
Intern 初始化后 MPS 驱动分配 8.80 GiB。
按过关条目数选定 Intern-Decision-4B（2 对 2）。
通过的条目 grounded_reason, stay_fit。正式权重仍由 C4 冻结流程登记。

Intern 使用 `scripts/devtools/decision_service.py --device mps`，通义使用固定版 `jevmlx serve`。体检入口为 `python -m eval.commerce.soft`，通义一组另加 `--fit-temperature`。MPS 内存通过 `decision_service.py --show-memory` 读取，体检样本只跑一遍。
