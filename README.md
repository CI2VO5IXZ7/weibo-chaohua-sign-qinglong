# weibo-chaohua-sign-qinglong

面向青龙面板的安卓微博超话签到脚本。脚本读取单账号环境变量 `status_taobudiao`，分页获取已关注超话，跳过今日已签到项，并逐项执行待签到操作。每次执行结束后只发送一条汇总通知。

## 功能

- 保留安卓微博超话列表、签到与游标分页流程
- 支持单账号环境变量 `status_taobudiao`
- 输出逐项签到状态和成功、已签、失败、跳过汇总
- 通过青龙标准 `notify.py` 的 `send` 函数发送一次通知
- 在没有 `notify.py` 时尝试兼容常见的 `sendNotify.py`
- 对缺失或无效环境变量、HTTP/JSON/分页错误及未预期异常发送失败汇总
- 通知失败不会改变签到任务原本的退出状态

## 安装

### 青龙面板

1. 将 `chaohua_sign_android.py` 上传到青龙脚本目录，或通过青龙订阅拉取本仓库。
2. 在“依赖管理”的 Python3 分类中安装 `requests`。
3. 确认脚本运行目录可以导入青龙自带的 `notify.py`。
4. 在“环境变量”中新增并启用 `status_taobudiao`。
5. 新建定时任务，例如：

```text
task chaohua_sign_android.py
```

Cron 示例 `10 9 * * *` 按青龙容器时区执行。请根据面板显示的下次运行时间确认时区。

### 本地测试环境

```bash
python3 -m pip install -r requirements.txt
```

## 配置 `status_taobudiao`

该变量必须是安卓微博 App 请求以下接口时产生的完整 HTTPS 请求 URL：

```text
/2/statuses/container_timeline_topicsub
```

URL 必须属于 `api.weibo.cn`，并包含脚本所需的 `aid`、`c`、`from`、`gsid` 和 `s` 参数。项目不提供凭据示例；请只在自己的青龙环境变量中保存真实值，不要写入脚本、README 或仓库文件。

当前仅支持一个账号，不读取 `weibo_my_cookie`、`status_tianqi` 或其他账号变量。

## 通知

脚本优先执行：

```python
from notify import send
```

实际实现采用运行时导入，以便在普通 Python 环境中也能执行测试。如果标准模块不可用，会尝试 `sendNotify.py` 中同名的 `send` 函数。

通知渠道由青龙的通知环境变量统一配置。请按照当前青龙版本中 `notify.py` 的说明设置对应渠道变量；本项目不保存或转发这些通知凭据。通知标题固定为“微博超话签到”，正文包含逐项结果、汇总和最终状态。

若通知模块不可用或发送失败，日志会输出脱敏的 `[通知警告]`，签到任务仍保持原本的退出状态。任务成功且通知失败时仍退出 0；签到流程失败时仍退出 1。

## 使用与退出状态

手动运行：

```bash
python3 chaohua_sign_android.py
```

青龙运行：

```text
task chaohua_sign_android.py
```

- 退出 0：所有识别到的项目均签到成功或已经签到。
- 退出 1：配置错误、请求/解析/分页错误、未预期错误，或存在签到失败/跳过项。
- 已经签到的超话不会触发随机等待；只有实际发出签到请求后才短暂等待。

## 安全注意事项

`status_taobudiao` 包含登录凭据，等同敏感信息。请务必遵守：

- 不要提交、上传或分享 `status_taobudiao` 的值。
- 不要提交 `status_taobudiao.txt`、HAR 抓包、凭据 URL、Cookie、Token、日志或截图中的认证参数。
- 不要在 Issue、Pull Request、聊天记录或公开日志中粘贴完整请求 URL。
- 凭据泄露后应立即在微博侧使会话失效，并重新获取请求信息。

脚本和通知会避免输出完整请求 URL、查询串及常见认证字段，但这不能替代妥善保管本地文件和青龙环境变量。

## 测试

离线单元测试不会访问网络，也不需要真实凭据：

```bash
python3 -m unittest -v
```

编译检查：

```bash
python3 -m compileall -q chaohua_sign_android.py test_chaohua_sign_android.py
```

## 限制

- 仅支持单账号和当前适配的安卓微博接口结构。
- 仅执行已关注超话签到，不包含发微博功能。
- 微博可能调整接口、触发风控或要求人工验证；此时需在 App 中确认登录状态并更新环境变量。
- 本项目不保证长期接口可用，也不会绕过验证码、风控或账号限制。
- 通知能力依赖青龙提供的通知模块及用户自己的渠道配置。
