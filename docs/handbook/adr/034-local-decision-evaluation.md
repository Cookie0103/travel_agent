# ADR-034 本机决策模型评估软性条目

日期：2026-11-28
状态：两套模型实机体检完成，选择 Intern-Decision-4B / MPS

## 模型来源与运行方式

- 首选 InternLM 发布的 Intern-Decision-4B，Hugging Face 修订 38c9daf，Apache-2.0。语言权重两片 4.26 GB、4.15 GB，投影权重 54.5 MB，视觉权重 613 MB，仓库合计约 9.11 GB。随模型的 DecisionEngine 是 HF 后端。使用 torch 2.9.1 和 transformers 5.14.1 在 Mac MPS 完成体检。[权重文件](https://huggingface.co/internlm/Intern-Decision-4B/tree/38c9daf) · [发布说明](https://huggingface.co/internlm/Intern-Decision-4B/blob/main/README.md)
- 备选 mlx-community/Qwen3.8-27B-4bit 修订 b935172，Apache-2.0。三个 model-0000x-of-00003.safetensors 合计约 16.1 GB，通过 MIT 许可的 jevmlx 本地服务返回选项概率。该量化包与 A7 的 Ollama 权重是不同文件，单列授权和版本。[MLX 权重文件](https://huggingface.co/mlx-community/Qwen3.8-27B-4bit/tree/b935172) · [jevmlx](https://github.com/bnsd55/jevmlx)

## 接口与验收

统一使用回环地址 POST /v1/systemone，状态里只放本条例子需要的事实。每项用有序的「是」「否」选项提问两次，保留两次概率和平均值。记录检查项、状态、模型、权重版本与内容哈希。无模型可用或未过体检的条目保留零权重。首选与备选使用同一批中文例子，实测获选模型后锁住权重版本。备选只校准概率温度。

实机结果见[中文软性条目体检](../../phase2/evidence/local-decision-health-v1.md)。两套模型同为 2 项通过，采用预先指定的首选。未通过的节奏条目权重为零。
