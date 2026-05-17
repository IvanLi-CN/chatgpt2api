# KaisouMail 邮箱 Provider 演进历史（#4bp4z）

> 这里记录会影响 Agent 理解“为什么一步步变成现在这样”的关键演进；单次任务流水账不放这里，规范正文仍以 `./SPEC.md` 为准。

## Decision Trace

- 新增本 spec，用于固定 `kaisoumail` provider 的最小配置面和 API 契约。

## Key Reasons / Replacements

- KaisouMail 已提供 API Key、邮箱创建和消息读取能力；本项目只需作为消费者接入，不需要复制域名管理能力。

## References

- `./SPEC.md`
- `./IMPLEMENTATION.md`
