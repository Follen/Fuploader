# ModUs 与 ModUs.Creator 操作

完整字段、状态机、接口映射及明确缺口见[平台字段总表](platform-fields.md#modus)。两套官方客户端都属于 ModUs，但 Fupload 按操作选择本地登录来源。

## 两种登录来源

- 插件项目、版本和 ZIP 发布默认使用 ModUs.Creator 的 CurrentUser DPAPI token 文件。
- 云备份、配置分享、WA、主客户端资源查询默认使用 ModUs 主客户端会话。
- 分别执行 modus session doctor --client creator 和 --client main。不要因其中一项成功就假定另一项已登录。

主客户端按固定官方 renderer origin 的当前 LevelDB 活跃表/WAL及 sequence 读取会话，处理删除墓碑；不扫描历史 token 逐个尝试。Creator 使用官方鉴权头格式，已有 Bearer 前缀不重复拼接。

本机两套登录源对两类只读接口都曾被服务端接受；这不改变默认来源，也不保证作者权限、账号身份或全部 API 范围相同。禁止输出或保存 token、DPAPI明文、签名上传地址。

## 插件项目和版本

project create/edit 使用官方 choose_game、basic_info、license 状态机的完成快照 project_state。实际字段覆盖顺序、可清空字段、发布平台与订阅限制见总表，不把 UI 快照本身直接发送到项目接口。

版本 ZIP 会解析 MD5、压缩/解压尺寸、TOC 与兼容版本。明确提供的摘要和尺寸必须与文件一致；仅编辑 metadata 时不能静默丢弃 schema 接受的字段。发布后按项目及版本读回；上传对象成功不代表版本登记成功。

带 ZIP 时，默认 path 使用官方的 modus/wow/addons/{projectId}/files/{fileId}.zip。显式 path 原样提交，随后核对保存的文件身份、路径、MD5、尺寸，并从官方 CDN 下载完整包验证；非官方地址需人工核验。路径修改或上传后的下载验证失败会返回 verification_required，不自动重发写入。仅 metadata 编辑且省略 path 时保留原路径。changelog 的显式 null 或空白在 update/edit 中发送官方 `<null>` 清空标记，非空正文原样保留。

真机对照中，首次访问 CDN 前完成的同一 fileId 二进制替换，完整包字节、MD5 和尺寸均验证通过；已访问过的下载地址则可能仍返回旧缓存，八小时后复查仍见旧包。此时作者记录已更新也会保留 verification_required，不能重复上传来处理缓存。plugin upload 创建新 fileId 的独立版本，不会自动替换或删除旧版本。

## 配置、WA 与备份

主客户端使用 server_type（--build 为别名）选择游戏分支。读取分页与写入正文不包含 CLI 的 handler/platform/resource 等内部字段。稀疏编辑先读取详情，保留未指定字段；create 的默认平台不能重置已有配置。

配置 content 是编辑器序列化 HTML/资源标记，content_text 是纯正文；原始 WA 的 code_text 是另一类内容，不能混同。清空套餐及角色相关字段按官方完整表单行为处理，不能假定 null 一定会传给服务端。

backup generate 只复制明确目录及角色，upload 验证本地清单与实际目录。上传事务记录用于防止模糊创建被重复提交，不包含鉴权凭据或签名 URL。Create 没有返回 ID 时，只能用本次唯一 manifest 对象从新记录中确认。

删除先预览，再用明确 backup_ids 与 confirm_delete=true；已引用备份拒删。未知关联停止整批，受保护项有单项结果；请求不确定不重放 DELETE。
