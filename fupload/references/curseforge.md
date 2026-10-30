# CurseForge 作者上传

当前 Fupload 提供公开项目查询、上传选项及向已有项目发布 ZIP。完整字段与官方支持/尚未实现的区分见[平台字段总表](platform-fields.md#curseforge)。

## 凭据

npm 安装或首次启动会保留/初始化 ~/.fupload/curseforge.env：CURSEFORGE_AUTHOR_ID、CURSEFORGE_API_KEY、CURSEFORGE_UPLOAD_TOKEN。作者 ID 不是密钥；API key 和 upload token 由用户自行填写，不经聊天、argv 或发布 JSON 输入。先运行 curseforge session doctor，不能打印 env 文件内容。

公开查询使用 Core API；上传使用作者 Upload API。两者域名、凭据和权限不同，不用 Studios API 替代。

## 查询与发布

project list 根据作者 ID 查询公开 WoW 项目并完整翻页。authorId 代表作者是项目成员，不只代表第一作者/主要所有者；空列表不证明没有私密、草稿或待审核项目。

上传先查 plugin game-versions。选择当前返回的版本 ID/名称，或使用 parent_file_id 走父文件分支；父文件分支不能同时提交版本字段。检查 ZIP、changelog、release_type、依赖关系和手动发布设置，再按目标叶子 help 构造 JSON。

当前上传动作只核对返回的正整数文件 ID，表示平台已接收；工具尚未实现后续文件处理/审核状态查询，需要到作者网站确认，不能报告已公开发布。网络结果不确定时先核对远端记录，不重复提交。

官方 Upload API 已有 update-file 元数据编辑能力；当前 Fupload 没有对应写命令。不能将“工具未实现”写成“平台不支持”。项目创建仍需按官方作者网站流程操作。
