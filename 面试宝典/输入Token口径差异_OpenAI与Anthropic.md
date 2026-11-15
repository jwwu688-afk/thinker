# 输入 Token 口径差异：OpenAI vs Anthropic

> 一句话结论：**OpenAI 的 `prompt_tokens` 已经把缓存命中算进去了，分母直接用 `prompt_tokens`；Anthropic 的 `input_tokens` 不含缓存读写，真正的输入量是 `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` 三者之和。**

---

## 1. 问题背景

两家都在计费时对「输入 token」做拆分，但拆分的**口径（字段含义）**相反：

| 维度 | OpenAI | Anthropic |
|------|--------|-----------|
| 主字段 | `prompt_tokens` | `input_tokens` |
| 主字段是否已含缓存命中 | ✅ 已包含 | ❌ 不含 |
| 缓存信息放哪 | 主字段下面的 `details` 子字段 | 与主字段**平级**的独立字段 |

这就导致一个常见错误：**用 OpenAI 的思维去读 Anthropic 的返回**，以为 `input_tokens` 就是全部输入量，结果把「缓存读」和「缓存写」这两块漏掉了，算出来的成本（或吞吐）偏低。

---

## 2. OpenAI 系：`prompt_tokens` 已包含缓存命中

OpenAI 的 `usage` 结构里，`prompt_tokens` 是**本次请求全部的输入 token 总数**，缓存命中部分只是它的一个子集，放在 `prompt_tokens_details.cached_tokens` 里做明细，**并不从主字段里减掉**。

### 2.1 字段结构（Chat Completions）

```json
"usage": {
  "prompt_tokens": 2006,
  "completion_tokens": 300,
  "total_tokens": 2306,
  "prompt_tokens_details": {
    "cached_tokens": 1920,
    "cache_write_tokens": 0
  }
}
```

### 2.2 口径关系

```
prompt_tokens = 未缓存输入 + 缓存命中（cached_tokens）
```

即：`cached_tokens`（1920）是 `prompt_tokens`（2006）的**一部分**，而不是额外的量。

因此：

```
真正的输入总量（分母） = prompt_tokens
```

- 要算「总输入 token 数」→ 直接取 `prompt_tokens`，**不要再加** `cached_tokens`（加了就是重复计算）。
- 要算「缓存命中率」→ `cached_tokens / prompt_tokens`。
- 要算「未缓存输入」→ `prompt_tokens - cached_tokens`。

> 补充：Responses API 里对应字段名为 `input_tokens`，缓存明细在 `usage.input_tokens_details.cached_tokens`，口径一致——`input_tokens` 同样**已含**缓存命中。OpenAI 无论哪个 API 都是「主字段含全部、明细只做拆分」。

---

## 3. Anthropic 系：三个字段平级相加才是分母

Anthropic 的 `input_tokens` 语义和 OpenAI 相反：它**只代表「最后一个缓存断点之后、既没读缓存也没写缓存」的新输入 token**，缓存相关的量被拆成了两个**平级**的独立字段。

### 3.1 字段结构（Messages API）

```json
"usage": {
  "input_tokens": 2048,
  "cache_read_input_tokens": 1800,
  "cache_creation_input_tokens": 248,
  "output_tokens": 503
}
```

三个字段含义：

| 字段 | 含义 |
|------|------|
| `input_tokens` | 最后一个缓存断点之后的**新输入**（未命中缓存、也不是缓存写） |
| `cache_read_input_tokens` | 从缓存**读**到的 token 数（命中） |
| `cache_creation_input_tokens` | 本次**写入**缓存的 token 数 |

### 3.2 口径关系

```
真正的输入总量（分母） = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
```

官方文档明确给出这条公式：`total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`。

⚠️ 关键陷阱：**`input_tokens` 不是全部输入**。官方举例——一个 200k token 的文档已缓存，用户又问了一句 50 token 的问题，此时返回的是：

```json
{
  "cache_read_input_tokens": 200000,
  "cache_creation_input_tokens": 0,
  "input_tokens": 50
}
```

如果只看 `input_tokens = 50`，就会把 20 万 token 的输入量完全漏掉。真正的输入总量是 200,050。

---

## 4. 一句话对照

| | OpenAI | Anthropic |
|---|--------|-----------|
| 主字段 | `prompt_tokens` | `input_tokens` |
| 主字段含义 | **全部输入**（含缓存命中） | 仅**新输入**（不含缓存读写） |
| 缓存量是否独立于主字段 | 否，是主字段的子集 | 是，与主字段平级 |
| 输入总量（分母） | `prompt_tokens` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` |
| 常见错误 | 多加了 `cached_tokens` | 漏加了两个 cache 字段 |

---

## 5. 为什么会有这种差异

本质是**「一个总数 + 子集拆分」** vs **「三个互斥部分相加」**两种计费数据模型：

- **OpenAI**：先给一个总数（`prompt_tokens`），再用 `details` 告诉你其中多少是缓存命中。数据模型是「整体 + 明细」。
- **Anthropic**：把输入切成三段互不重叠的独立字段（新输入 / 缓存读 / 缓存写），每段各自计价，没有「总输入」这一字段，要自己加。数据模型是「分段相加」。

两者在语义上等价，只是拆分维度和字段组织方式不同，导致跨家迁移或做多模型成本统计时极易踩坑。

---

## 6. 上下文窗口怎么算

> 核心结论：**上下文窗口（context window）的算法与「计费分母」是两个不同的问题。缓存命中能省钱，但照样占窗口。缓存改变的是「价格」，不是「容量」。**

### 6.1 上下文窗口是什么

上下文窗口是模型在**一次请求里能处理的最大 token 预算**，是模型的「工作内存」。它包含：

```
上下文窗口 = 系统提示 + 全部历史消息（含工具结果/图片/文档）
           + 工具定义 + 本次模型输出（含思考/推理 token）
```

- **输入和输出一起算**：窗口是「输入 + 输出」的总预算，不是只算输入。模型要在一个窗口里同时容纳「读进来的全部内容」和「它要吐出去的答案」。
- **输出有单独上限**：模型不能把整个窗口都用来输出。各家对单次输出另有 `max_tokens`（如 1M 窗口的模型通常最多输出 128k），推理模型的思考 token 也是从输出预算里扣。

### 6.2 关键：缓存命中同样占窗口

这是最容易和「计费」搞混的地方。**两家官方都明确：缓存命中（cached）的 token 依然占据上下文窗口。**

- **OpenAI**：`prompt_tokens`（含 `cached_tokens`）整体计入窗口，缓存只让这部分更便宜、更快，不减容量。
- **Anthropic**：官方原文——使用 prompt cache 时，输入被拆成 `input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`，**三者都计入窗口**。缓存改变的是你对这些 token 付多少钱，而不是它们算不算数。

一句话：**缓存省的是「钱」和「延迟」，不省「窗口容量」。** 一个 20 万 token 的已缓存文档，哪怕读它只花 0.1× 的价，它依然吃掉 20 万 token 的窗口。

### 6.3 所以「占用窗口的总输入」怎么算

```
OpenAI：  窗口输入量 = prompt_tokens           （本身已含缓存命中）
Anthropic：窗口输入量 = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
```

注意：**算窗口占用和算计费分母，在这里用的是同一个数**——这正好和第 4 节那张对照表一致。区别只在于：

- 算「占了多少窗口」→ 用上面的总量（缓存命中照算）。
- 算「花了多少钱」→ 缓存命中部分按折扣价，未命中按原价，是另一个维度。

### 6.4 一张图看清两个维度

| 维度 | 缓存命中的 token | 结论 |
|------|-----------------|------|
| 占上下文窗口 | ✅ 照算 | 缓存不省容量 |
| 计费价格 | ✅ 折扣 | 缓存省的是钱 |

---

## 参考

- OpenAI：Prompt caching 官方文档（`cached_tokens` / `cache_write_tokens` 字段说明）
- Anthropic：Prompt caching 官方文档（`input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` 三字段及 `total_input_tokens` 求和公式）
