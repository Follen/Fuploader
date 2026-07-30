# 网易 DD 指定频道时间段消息拉取调研

## 示例目标映射

UI 和运行时日志已经确认用户给出的目标：

| 展示字段 | 内部字段 | 值 |
| --- | --- | --- |
| 空间号 | `teamId` | `16888` -> `144686` |
| 空间名 | - | `露露缇娅的专属空间` |
| 分类 | category ID | `露露的插件包 \| 提问与反馈` -> `G10150764` |
| 子频道 | `channelId` | `提问与反馈 至暗之夜` -> `10075340` |
| 频道类型 | - | text |

展示空间号、`teamId` 和 `channelId` 是不同标识。历史消息接口必须使用内部 `channelId`。

## 历史消息接口

```http
GET https://api.cc.163.com/v1/mixteamchat/chatMsg/list
Authentication: <jwt>
```

查询参数：

```json
{
  "channelId": "10075340",
  "msgId": 0,
  "isAsc": 0
}
```

客户端方法 `reqHistoryData(msgId, isAsc, reqType)` 实际只把 `channelId`、`msgId`、`isAsc` 发到服务端；`reqType` 是客户端内部状态，不是接口参数。

运行时观察到：

```text
reqType=1, channelId=10075340, msgId=0,     isAsc=0
reqType=5, channelId=10075340, msgId=30123, isAsc=1
reqType=2, channelId=10075340, msgId=30124, isAsc=0
```

由客户端代码和运行时行为可得：

- `msgId=0,isAsc=0`：取最新一页。
- `msgId=<当前最小 msgId>,isAsc=0`：向更早消息翻页。
- `msgId=<游标>,isAsc=1`：向更新消息翻页。
- 实测每页 30 条。
- `sendTime` 是 Unix 毫秒时间戳。
- 响应含 `channelId`、`msgList`；单条消息含 `msgId`、`sendTime`、发送者、消息类型/内容、引用、状态和表情等元数据。

## A 到 B 的拉取方案

所检查的客户端请求没有 A/B 时间参数，因此时间范围要在游标分页后本地过滤。建议统一使用半开区间：

```text
A <= sendTime < B
```

算法：

1. 将展示空间/频道定位到内部 `channelId`。
2. 没有已有游标时，以 `msgId=0,isAsc=0` 获取最新页。
3. 以当前页最小 `msgId` 为游标、`isAsc=0` 持续向前翻页。
4. 每页只保留满足 `A <= sendTime < B` 的消息。
5. 当页面最早 `sendTime < A`，或返回空页，或游标不再前进时停止。
6. 按 `(channelId,msgId)` 去重。
7. 最终按 `(sendTime,msgId)` 升序输出。

伪代码：

```text
cursor = 0
seen_cursors = set()
results = []

while cursor not in seen_cursors:
    seen_cursors.add(cursor)
    page = history(channelId, msgId=cursor, isAsc=0)
    if page.msgList is empty:
        break

    results += messages where A <= sendTime < B
    if min(page.sendTime) < A:
        break

    next_cursor = min(page.msgId)
    if next_cursor == cursor:
        break
    cursor = next_cursor

dedupe results by (channelId, msgId)
sort results by (sendTime, msgId)
```

## 边界处理

- 同一毫秒可能有多条消息，排序和去重必须带 `msgId`。
- 应检测重复游标和重复页面，防止无限循环。
- 撤回、删除、审核态消息应按 `msgStatus` 处理，不能当普通文本输出。
- 富文本、图片、文件、引用和系统消息需要按类型解析；不能假设 `content` 总是纯文本。
- JWT 过期或时间戳无效时走刷新流程，再重试当前只读页。
- 若 B 远早于当前时间，从最新页倒翻会有较高请求成本。后续可维护每频道的时间到 `msgId` 检查点，但不能假定服务端支持按时间定位。

## 尚未解决

- 示例 `16888` 映射已确认，但尚未找到任意展示空间号到内部 `teamId` 的通用、稳定解析接口。
- 尚未用一个用户给定的真实 A/B 区间完成端到端导出验证。
- 本次没有把任何消息正文或账号相关响应保存到调研目录。

## 无头只读实测

关闭 DD GUI 后使用本目录的 `headless_probe.py history --channel-id 10075340 --hours 3`，
在 2026-07-30 19:07:27 至 22:07:27（UTC+08:00）窗口内完成 1 页分页，筛出
7 条消息。响应字段已确认包含 `msgId`、`sendTime`、`senderNickname`、
`msgType`、`msgStatus` 和 `content`；探针只在终端输出筛选后的字段，不保存
原始 JSON。发送者字段不是嵌套对象，解析时应使用 `senderNickname`。

稳定独立设备模式下又完成一次并发验证：GUI DD 保持登录，sidecar 使用固定
`clientNo` 获取 JWT，在 2026-07-30 19:21:31 至 22:21:31（UTC+08:00）窗口内
分页 1 页并筛出 7 条消息。GUI 未被顶下线。
