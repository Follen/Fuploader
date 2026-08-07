# 新手盒子官方 CLI 优先路由完整目标规格

## 激活与通道选择

Fupload 继续只由用户显式调用。用户选择新手盒子插件、WA/字符串或配置分享后，Skill 先用
本机事实检测 `ncc`。已安装时默认选择官方 Creator Center CLI，并检查版本、help、docs 与
登录状态；只有用户显式要求使用第三方 Python 管理工具时才选择现有 Python provider。不得
同时向两个通道提交同一写入。

官方 CLI 的安装契约是 Node.js >= 18 与
`npm i -g @newbeebox/newbeebox-creator-center-cli@latest`。Agent 只能在确认安装成功后运行
`ncc -V`、`ncc --help`、`ncc docs` 和 `ncc whoami -o json`。当 `ncc` 未安装时，Agent 先
询问用户是否采用官方 CLI；用户同意后才安装依赖或全局 npm 包，并在安装后逐项验证。`ncc
docs` 与叶子 `--help` 定义当前安装版本的运行时行为，Skill 内快照只用于安装前规划和离线参考。

当官方 CLI 缺少目标能力时，Agent 说明官方边界并等待用户选择。只有用户显式要求第三方
Python 管理工具时，才重新读取远端状态、切换通道并重新规划确认；不得自动 fallback，也不得
凭相似命令名猜测未文档化能力。

## 文档引用

Skill 包包含官方 `https://creator.newbeebox.com/md/cli-docs` 的完整 UTF-8 Markdown 快照，保留
安装、快速上手、AI 协作、全部命令、push 参数、`ncc.json`、bundle、CI、退出码、错误码和
FAQ。引用文件标注来源与获取日期，但不混入令牌、账号或本机路径。

每次新手盒子任务只加载与目标资源有关的章节；执行前仍运行 `ncc docs` 和叶子 help。官方
文档更新导致静态快照与本机版本不一致时，以本机 `ncc docs`/help 为当次命令契约，并向用户
说明引用快照需要更新，不能把旧参数提交给新版本。

## 凭据交付

凭据优先级如下：

1. 复用用户已通过官方 `ncc login` 建立的本机登录，以 `ncc whoami -o json` 验证；
2. 自动化环境由用户在 Agent 进程启动前预置 `NCC_TOKEN`，命令仅继承环境变量；
3. 缺少认证时，让用户在自己的终端执行官方登录或设置环境变量，再重新验证身份。

Agent 不要求用户把令牌粘进对话，不把真实值放入 `--token` 参数、shell 历史、项目环境文件、
JSON 输入、发布记录、日志、测试、Skill/reference 或 Git。安装完成后，Agent 告知用户前往
官方 CLI 令牌页创建凭据，并让用户在自己的终端完成 `ncc login`；之后只用 `whoami` 验证。
若用户已在对话中暴露令牌，Agent 不复述或使用该值，提示从 CLI 令牌管理页吊销并创建替代
令牌。

## 执行与验证

Agent 使用 `-o json` 获取稳定输出，按官方退出码区分成功、业务错误、鉴权失败和网络错误。
插件写入使用 create/edit/init/push/pack/sync/changelog；WA 使用 publish/edit/init/pull/push；
配置分享使用 publish/init/pull/push；分类、版本、云备份、媒体、引用和评论使用相应只读或
附属命令。官方文档声明只能网页或桌面客户端完成的能力保持受限。

写入前继续执行 Fupload 的本地材料调查、远端目标确认、动态候选查询、完整计划和一次明确
确认。支持 dry-run 的命令必须先 dry-run。写入后立即使用 info/list/versions 或相应只读命令
核对目标、版本与关键字段；网络错误不得自动重发写入，必须先读回判断。

插件目录关联保留 `ncc.json`、`.nccignore`、bundle 与 TOC 结构规则。`sync --yes`、删除或附件
移除等不可恢复动作不得仅凭通用发布确认执行，必须展示准确目标和覆盖/删除影响后另行确认。

## 与 Python 执行层的边界

现有 Python CLI 保持可分发和可测试，不读取 `NCC_TOKEN`，也不复制官方 CLI 的凭据文件。
一次计划只能选择一个写入通道；切换通道前必须重新读取远端状态并重新生成计划，避免对同一
对象重复创建、重复上传版本或用陈旧详情覆盖。
