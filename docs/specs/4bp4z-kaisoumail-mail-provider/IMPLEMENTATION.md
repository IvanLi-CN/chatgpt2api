# KaisouMail 邮箱 Provider 实现状态（#4bp4z）

> 当前有效规范仍以 `./SPEC.md` 为准；这里记录实现覆盖、交付进度与 rollout 相关事实，避免这些细节散落到 PR / Git 历史里。

## Current Status

- Implementation: 已实现
- Lifecycle: active
- Catalog note: 外部邮箱 provider 接入。

## Coverage / rollout summary

- `KaisouMailProvider` 已接入 `POST /api/mailboxes`、`GET /api/messages` 和 `GET /api/messages/:id`。
- 注册配置页面已新增 `kaisoumail` 类型，并仅展示 `ApiURL` 与 `ApiKey` 字段。
- 单元测试覆盖创建邮箱、列表验证码、详情 fallback、鉴权失败不重试和 429 重试。

## Remaining Gaps

- 真实 KaisouMail API Key 的生产端到端验证未在本地执行。
- UI 视觉证据待补充。

## Related Changes

- `services/register/mail_provider.py`
- `web/src/app/register/components/register-card.tsx`
- `test/test_cloudflare_temp_mail_provider.py`

## References

- `./SPEC.md`
- `./HISTORY.md`
