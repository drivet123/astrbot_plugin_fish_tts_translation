# AstrBot Fish Audio 翻译语音插件

在 OneBot v11 QQ 聊天中，按概率把 Bot 的短文本回复翻译成目标语言，由 LLM 补充 Fish Audio S2 情感标签，再使用指定音色生成并发送 WAV 语音。插件等待原回复发送完成后再单独补发语音，不修改原消息链，也不会生成或发送额外文字。

## 功能与限制

- 仅支持 `aiocqhttp`（OneBot v11）平台，例如 NapCat、Lagrange。
- 仅处理纯文本回复（允许 QQ 的 @ 和引用组件）；空消息、超长消息和混合媒体消息不会触发。
- 对模型回复优先使用 `on_llm_response` 捕获的完整全文，避免分段发送后只转换最后一句；其他回复会合并同一结果中的全部文本段。
- 字数限制针对去除首尾空白后的原文，不包括后续情感标签。
- 翻译和情感标注使用当前会话的聊天模型，共用一次 LLM 调用。
- 使用 Fish Audio S2 方括号标签，例如 `[happy]`、`[whispering]`。
- 默认模型为 `s2.1-pro-free`，格式为 WAV，使用稳定性优先的 `normal` 延迟模式完整合成。
- 在 WAV 末尾补充 800ms 静音，降低 QQ 播放或协议转换截断尾音的概率；无效 WAV 会保留原始音频。
- 翻译、合成或语音发送失败时不向聊天发送错误消息，不自动重试。
- 语音在原回复之后作为独立消息发送。

## 安装

将本插件放入 AstrBot 的 `data/plugins/` 目录并安装 `requirements.txt` 中的依赖。AstrBot 版本要求为 `>=4.5.7,<5`。

## 配置

在 AstrBot WebUI 的插件配置页面设置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 总开关，配置完成后启用 |
| `probability` | `0.15` | 每条符合条件的消息独立判定，范围 0～1 |
| `max_text_length` | `40` | 原文字符数上限，超过则不触发 |
| `target_language` | `日语` | 可改为英语、韩语等 |
| `fish_api_key` | 空 | Fish Audio API Key |
| `fish_reference_id` | 空 | 要使用的 Fish Audio 音色模型 ID |
| `fish_proxy` | 空 | 可选的 Fish Audio 网络代理，例如 `http://127.0.0.1:7890` |

API Key 可在 [Fish Audio API Keys](https://fish.audio/app/api-keys) 页面创建。音色 ID 可在 Fish Audio 音色库或自己创建的音色模型中获取。

### 网络代理

如果出现 `All connection attempts failed` 或连接 `api.fish.audio` 超时，可在 `fish_proxy` 中显式填写代理地址。该代理只用于 Fish Audio 请求，不影响 AstrBot 的其他网络连接。

- AstrBot 直接运行在 Windows 上：填写本机代理监听的地址，例如 `http://127.0.0.1:7890`，端口以代理软件为准。
- AstrBot 运行在 Docker 中：容器内的 `127.0.0.1` 指向容器自身，不能使用宿主机代理；可尝试 `http://host.docker.internal:7890`，并确认代理软件允许局域网连接且监听对应网卡。
- 代理地址包含账号密码时请注意保管，插件不会主动记录该配置。

## 数据与费用

命中概率后，原始短句会发送给当前会话配置的翻译模型，带情感标签的译文会发送给 Fish Audio。翻译模型可能产生费用。`s2.1-pro-free` 是 Fish Audio 当前用于测试、开发和较小规模使用的免费模型，但仍受其平台配额、服务条款及可用性限制。

插件不会在日志中主动输出 API Key、原文或音频 Base64，也不会创建临时音频文件。

## 验证

单元测试使用模拟的 AstrBot 和 Fish Audio 接口，不需要真实 API Key：

```bash
python -m unittest discover -s tests -v
ruff check .
```

真实环境验收时，建议先在测试群将 `probability` 设为 `1`：

1. 发送一条不超过字数上限的消息，确认收到原文和日语语音。
2. 修改目标语言和音色 ID，确认语音随之变化。
3. 将 `max_text_length` 调小，确认超长消息只有原文。
4. 使用错误 API Key 或音色 ID，确认仍能收到原文且插件不崩溃。
5. 将概率恢复为所需值。

## 参考

- [AstrBot 消息事件钩子](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)
- [AstrBot 语音组件](https://docs.astrbot.app/dev/star/guides/send-message.html)
- [Fish Audio TTS](https://docs.fish.audio/features/text-to-speech)
- [Fish Audio 情感标签](https://docs.fish.audio/developer-guide/core-features/emotions)
