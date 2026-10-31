# 新手盒子 Python 通道操作

此页适用于用户明确选择的第三方 Python 管理通道。官方 ncc 已安装时默认走官方通道，不静默改用 Python。两套通道字段不能互换。

完整 Python 字段与协议映射见[平台字段总表](platform-fields.md#newbee)。官方 ncc 0.1.29 的运行时文档见[官方 CLI 参考](newbee-official-cli.md)，升级后以 ncc docs 和叶子 --help 为准。

## 登录与读取

Python 复用当前 Windows 用户官方桌面 auth-store，通过固定官方服务交换 Creator 资源凭据。桌面备份 API 使用桌面 access token；Creator 资源凭据不能代替它。程序不接受用户提交 Cookie、token、域名或本地凭据路径。

先执行 newbee session doctor。分类、游戏分支/build、内容来源、订阅档位及期限均先查询。插件版本兼容使用 build 字符串；WA 的游戏版本用返回的数值 ID，二者不能混用。

## 创建与更新

插件先创建私密记录，上传并读回首版本后，才执行用户明确要求的公开审核。已有更新不能暗改可见性。public 与 submit_for_review 的配对条件见总表。

插件元数据、版本上传、历史 changelog 是不同动作；配置的正文编辑和备份内容更新也分开。edit/update 先读当前值，只覆盖明确字段。公开配置正文 content 是 HTML/Markdown 描述，不是原始 WTF；读取时完整保留，WA 导入串仍做摘要。

协作者与引用使用各自 set 动作替换完整关系；空数组表示清空。主记录成功读回后才处理关系；失败不盲目重发 create。引用的 `references[].type` 使用官方选择器的 `sourceType`：插件为 `1`、WA 为 `2`、配置为 `3`。`reference-search`/`reference-list` 返回的 `type` 是展示类型，可能使用另一套枚举，不能直接复制到 set；选择时保留目标 `id`，按当前资源填写 `type`。已实测展示类型分别为插件 `2`、WA `3`、配置 `4`。目标须能由官方引用搜索找到；新公开配置可能仍在审核，先只读检查状态与搜索结果，再提交关联。

## 配置与云备份

配置先选择 cloud_id，再检查插件、被忽略内容和 roleid；不要把客户端角色名称猜成 Creator 角色 ID。更换备份时重新核对所有子选择。

backup scan 列出本机候选，generate 按明确账号、服务器、角色与 include_common 生成本地包；upload/create 上传并读回。账号公共配置与每个角色分别打包。字体通过官方 nbb-core 上传选中文件，不接受调用者提供模块路径或接口地址。

删除必须先 delete-preview；写入只接受明确 backup_ids 和 confirm_delete=true。任何配置分享引用、缺失详情或不完整分页都拒删；每项前重查，删除后核对列表缺失，模糊结果不重发。

官方 ncc 的 cloudbackup 当前只有 list/info。Python 的生成、上传、改名和删除不意味着官方 CLI 也提供这些命令；官方独有的 home-page 等字段也不意味着 Python 已接受。

引用写后校验逐条按已确认的展示类型 `2/3/4` 转换到写入类型 `1/2/3`，再匹配类型和目标 ID。缺失、未知或冲突类型一律返回待核验；数字 ID 相同不能替代资源类型核对。
