# TDPFuzz 变体生成工具使用指南

## 简介

`genvariants_parallel.py` 是 TDPFuzz 项目中用于生成代码变体的核心工具，它利用大型语言模型（如 GLM-4.5-FLASH）对种子代码进行变异，生成多个变体用于模糊测试。

## 基本用法

### 命令行参数

```bash
python genvariants_parallel.py [选项] <输入文件>
```

### 常用命令示例

```bash
# 基本用法：生成5个变体，每个变体最多50个token，温度0.1
python genvariants_parallel.py -O ./preset/jsoncpp/initial/variants -L ./preset/jsoncpp/initial/logs -n 5 -m 50 -t 0.1 ./preset/jsoncpp/seed_genjson.py

# 使用特定模型生成变体
python genvariants_parallel.py -M glm-4.5-flash -O ./preset/jsoncpp/initial/variants -L ./preset/jsoncpp/initial/logs -n 5 -m 50 -t 0.1 ./preset/jsoncpp/seed_genjson.py

# 使用更多并发数加速生成（注意：GLM模型建议并发数不超过5）
python genvariants_parallel.py -j 5 -O ./preset/jsoncpp/initial/variants -L ./preset/jsoncpp/initial/logs -n 5 -m 50 -t 0.1 ./preset/jsoncpp/seed_genjson.py
```

## 参数详解

### 必需参数

- `<输入文件>`: 种子代码文件路径，例如 `./preset/jsoncpp/seed_genjson.py`

### 可选参数

#### 输出控制
- `-O, --output_dir`: 变体输出目录（默认：当前目录）
- `-L, --log_dir`: 日志输出目录（默认：logs）
- `-n, --num_variants`: 每个种子文件生成的变体数量（默认：1）

#### 模型设置
- `-M, --model_name`: 使用的模型名称（默认：codellama/CodeLlama-13b-hf）
  - 常用GLM模型：glm-4.6, glm-4.5-flash, glm-4-flash, glm-4, glm-3-turbo

#### 生成参数
- `-t, --gen.temperature`: 生成温度（默认：0.2）
  - 较低值（如0.1）生成更稳定的代码
  - 较高值（如0.7）生成更多样化的代码
- `-m, --gen.max-new-tokens`: 最大生成token数（默认：2048）
- `-r, --gen.repetition-penalty`: 重复惩罚（默认：1.1）

#### 变异器控制
- `--no-completion`: 禁用补全变异器
- `--no-fim`: 禁用FIM（中间填充）变异器
- `--no-splice`: 禁用拼接变异器

#### 其他设置
- `-s, --start_line`: 变异起始行（默认：0）
- `-j, --jobs`: 并发任务数（默认：16）
  - GLM模型建议不超过5，避免触发API限制

## 配置文件

### API密钥配置

#### 方法1：环境变量

```bash
# GLM API密钥
export GLM_API_KEY="your_glm_api_key_here"

# 多模型端点配置（可选）
export ENDPOINTS="glm-4.6:https://open.bigmodel.cn/api/paas/v4/chat/completions glm-4.5-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions"
```

#### 方法2：配置文件

创建 `~/.config/glm/token` 文件，内容为您的GLM API密钥：

```
your_glm_api_key_here
```

#### 方法3：使用ELMFuzz CLI配置（推荐）

使用ELMFuzz CLI工具配置API密钥：

```bash
# 设置GLM API密钥
elfuzz config --set glm.api_key "your_glm_api_key_here"

# 查看所有可配置选项
elfuzz config --list

# 获取特定配置值
elfuzz config --get glm.api_key
```

ELMFuzz CLI会自动将API密钥写入 `~/.config/glm/token` 文件，并创建必要的符号链接。

### 模型端点配置

#### 方法1：环境变量

```bash
export ENDPOINTS="glm-4.6:https://open.bigmodel.cn/api/paas/v4/chat/completions glm-4.5-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions"
```

#### 方法2：elmconfig.yaml文件

您可以通过 `elmconfig.yaml` 文件配置模型端点：

```yaml
model:
  endpoints:
    - glm-4.6:https://open.bigmodel.cn/api/paas/v4/chat/completions
    - glm-4.5-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions
    - glm-4-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions
```

### 并发数优化配置

工具会自动保存每个模型的最佳并发数到 `~/.config/tdpfuzz/best_jobs.json`：

```json
{
  "glm-4.6": 3,
  "glm-4.5-flash": 5
}
```

### 完整配置示例

以下是一个完整的配置示例，结合了ELMFuzz CLI和配置文件的使用：

```bash
# 1. 使用ELMFuzz CLI设置GLM API密钥
elfuzz config --set glm.api_key "your_glm_api_key_here"

# 2. 创建模型端点配置
cat > elmconfig.yaml << EOF
model:
  endpoints:
    - glm-4.6:https://open.bigmodel.cn/api/paas/v4/chat/completions
    - glm-4.5-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions
    - glm-4-flash:https://open.bigmodel.cn/api/paas/v4/chat/completions
EOF

# 3. 创建并发数配置目录和文件
mkdir -p ~/.config/tdpfuzz
cat > ~/.config/tdpfuzz/best_jobs.json << EOF
{
  "glm-4.6": 3,
  "glm-4.5-flash": 5
}
EOF

# 4. 运行变体生成工具
python genvariants_parallel.py -M glm-4.5-flash -O ./preset/jsoncpp/initial/variants -L ./preset/jsoncpp/initial/logs -n 5 -m 50 -t 0.1 ./preset/jsoncpp/seed_genjson.py
```

## 使用技巧

### 1. 提高代码质量

- 使用较低的温度（如0.1）生成更稳定的代码
- 对于GLM模型，工具会自动优化提示词以提高代码质量

### 2. 加速生成

- 适当增加并发数（GLM模型建议不超过5）
- 工具会自动测试并保存最佳并发数

### 3. 减少语法错误

- 工具内置了语法纠错功能，会自动尝试修复生成的代码
- 对于复杂错误，会使用GLM模型进行智能纠错

### 4. 选择合适的模型

- `glm-4.6`: 最新模型，代码质量最高，但速度较慢
- `glm-4.5-flash`: 快速模型，平衡质量和速度(限时免费)
- `glm-4-flash`: 速度最快的模型，适合大量生成

## 故障排除

### 1. API限制错误

如果遇到429错误（API并发限制）：
- 减少并发数（-j参数）
- 增加重试间隔
- 使用更快的模型（如glm-4.5-flash）

### 2. 语法错误过多

- 降低温度参数（-t）
- 使用更高质量的模型（如glm-4.6）
- 检查种子代码是否有语法问题

### 3. 生成速度慢

- 使用更快的模型（如glm-4.5-flash）
- 增加并发数（注意不要超过API限制）
- 减少最大token数（-m参数）

## 示例工作流

### 1. 基本工作流

```bash
# 1. 设置API密钥
export GLM_API_KEY="your_api_key_here"

# 2. 生成变体
python genvariants_parallel.py -M glm-4.5-flash -O ./variants -L ./logs -n 10 -m 100 -t 0.1 ./seed_file.py

# 3. 检查生成的变体
ls ./variants
```

### 2. 高级工作流

```bash
# 1. 创建配置目录
mkdir -p ~/.config/tdpfuzz

# 2. 创建最佳并发数配置
cat > ~/.config/tdpfuzz/best_jobs.json << EOF
{
  "glm-4.6": 3,
  "glm-4.5-flash": 5
}
EOF

# 3. 使用配置文件运行
python genvariants_parallel.py --config elmconfig.yaml ./seed_file.py
```