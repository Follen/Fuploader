package cli

import (
	"fmt"

	"fupload/internal/input"
	"fupload/internal/output"
	"fupload/internal/platform"

	"github.com/spf13/cobra"
)

func (a *app) newWACommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "wa",
		Short: "管理新手盒子 WA 字符串内容",
		Long: `覆盖新手盒子 WA 的查询、创建、元数据编辑、字符串新版本、版本日志和附属关系。

CLI 中每个写命令只执行一个最终业务动作；不提供草稿或删除命令。已有 WA 的编辑和发版工作流最终设置公开并可能进入审核。`,
		Example: `  fupload newbee wa list --output json
  fupload newbee wa create --input wa.yaml
  fupload newbee wa publish-version --input wa-version.yaml`,
	}
	cmd.AddCommand(
		a.newWAListCommand(), a.newWAGetCommand(), a.newWACategoriesCommand(), a.newWAAttachmentPathsCommand(),
		a.newWACreateCommand(), a.newWAEditCommand(), a.newWAPublishVersionCommand(), a.newWAMediaCommand(),
		a.newWAChangelogCommand(), a.newWACoAuthorCommand(), a.newWAReferenceCommand(), a.newWAShareCodeCommand(),
	)
	return cmd
}

func (a *app) newWAListCommand() *cobra.Command {
	var keyword string
	var offset, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出当前作者的 WA",
		Long: `分页列出当前账号在新手盒子创作者中心的 WA。

offset 从 0 开始；该命令只读，返回 WA ID、名称、公开和审核状态等服务端字段。`,
		Example: `  fupload newbee wa list
  fupload newbee wa list --keyword 酒仙 --offset 0 --page-size 50 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWAs(cmd.Context(), platform.ListOptions{Keyword: keyword, Page: offset, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.list", data, false)
		},
	}
	cmd.Flags().StringVar(&keyword, "keyword", "", "按 WA 名称过滤")
	cmd.Flags().IntVar(&offset, "offset", 0, "分页偏移，从 0 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 50, "每页数量，最大 100")
	return cmd
}

func (a *app) newWAGetCommand() *cobra.Command {
	var id int
	cmd := &cobra.Command{
		Use:   "get",
		Short: "读取一个 WA 的可编辑详情",
		Long: `按 WA ID 读取元数据和当前内容详情。

该命令只读；普通输出不得显示登录凭据或预签名 URL。Skill 在编辑前用它保留远端字段。`,
		Example: `  fupload newbee wa get --id 123
  fupload newbee wa get --id 123 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.GetWA(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.get", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "WA ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newWACategoriesCommand() *cobra.Command {
	var gameVersionID int
	cmd := &cobra.Command{
		Use:   "categories",
		Short: "列出指定游戏版本的 WA 分类",
		Long: `从新手盒子读取指定 game-version-id 可用的 WA 分类。

该命令只读；创建和编辑时应查询真实 ID，不能在 Skill 中硬编码。`,
		Example: `  fupload newbee wa categories --game-version-id 1
  fupload newbee wa categories --game-version-id 1 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if gameVersionID <= 0 {
				return fmt.Errorf("--game-version-id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWACategories(cmd.Context(), gameVersionID)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.categories", data, false)
		},
	}
	cmd.Flags().IntVar(&gameVersionID, "game-version-id", 0, "游戏版本 ID（必填）")
	_ = cmd.MarkFlagRequired("game-version-id")
	return cmd
}

func (a *app) newWAAttachmentPathsCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "attachment-paths",
		Short: "列出 WA 附件安装路径",
		Long: `读取新手盒子当前允许的 WA 附件安装路径和类型。

该命令只读，供 Agent 整理附件资料，不上传文件。`,
		Example: `  fupload newbee wa attachment-paths
  fupload newbee wa attachment-paths --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWAAttachmentPaths(cmd.Context())
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.attachment-paths", data, false)
		},
	}
}

func (a *app) newWACreateCommand() *cobra.Command {
	return a.newWAInputCommand("create", "创建一个新的 WA", `创建 WA 元数据和首个字符串版本。

输入 schema 为 fupload.newbee.wa.create.v1。game_version_id、name、wa_str、wa_log 和 string_mode 必填；单条字符串用 single，集合用 collection 并提供同序 wa_str_titles。未明确 public 时保持私有。`,
		`  fupload newbee wa create --input wa.yaml
  Get-Content wa.json | fupload newbee wa create --input - --output json
  fupload newbee wa create --input wa.yaml --dry-run`, "fupload.newbee.wa.create.v1",
		func(service platform.Service, cmd *cobra.Command, value platform.WAInput) (any, error) {
			return service.CreateWA(cmd.Context(), value)
		})
}

func (a *app) newWAEditCommand() *cobra.Command {
	return a.newWAInputCommand("edit", "编辑已有 WA 的元数据", `编辑已有 WA 的名称、说明、图片、分类、付费和频道字段，不发布新字符串版本。

输入 schema 为 fupload.newbee.wa.edit.v1，id 必填。该动作固定设置公开，可能提交或重新进入审核，但不代表审核通过。`,
		`  fupload newbee wa edit --input wa-edit.yaml
  Get-Content wa-edit.json | fupload newbee wa edit --input - --output json
  fupload newbee wa edit --input wa-edit.yaml --dry-run`, "fupload.newbee.wa.edit.v1",
		func(service platform.Service, cmd *cobra.Command, value platform.WAInput) (any, error) {
			return service.EditWA(cmd.Context(), value)
		})
}

func (a *app) newWAPublishVersionCommand() *cobra.Command {
	return a.newWAInputCommand("publish-version", "发布 WA 字符串新版本", `为已有 WA 发布一个字符串新版本。

输入 schema 为 fupload.newbee.wa.publish-version.v1，id、wa_str 和 wa_log 必填。命令先调用 get_next_version；version 留空时使用服务端返回值。成功后不会修改其他元数据。`,
		`  fupload newbee wa publish-version --input wa-version.yaml
  Get-Content wa-version.json | fupload newbee wa publish-version --input - --output json
  fupload newbee wa publish-version --input wa-version.yaml --dry-run`, "fupload.newbee.wa.publish-version.v1",
		func(service platform.Service, cmd *cobra.Command, value platform.WAInput) (any, error) {
			return service.PublishWANewVersion(cmd.Context(), value)
		})
}

type waWriteFunc func(platform.Service, *cobra.Command, platform.WAInput) (any, error)

func (a *app) newWAInputCommand(use, short, long, example, schema string, write waWriteFunc) *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use: use, Short: short, Long: long, Example: example,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WAInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != schema {
				return fmt.Errorf("schema must be %s", schema)
			}
			if err := validateWAInputLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa."+use, dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := write(service, cmd, value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa."+use, data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newWAMediaCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "media",
		Short: "上传 WA 媒体",
		Long: `显式上传 WA 封面或截图媒体并返回服务端引用。

媒体上传不会创建或编辑 WA；调用方应把返回引用写入后续结构化输入。`,
		Example: `  fupload newbee wa media upload --input media.yaml
  fupload newbee wa media upload --input media.yaml --dry-run`,
	}
	cmd.AddCommand(a.newWAMediaUploadCommand())
	return cmd
}

func (a *app) newWAMediaUploadCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "upload",
		Short: "上传一个 WA 媒体文件",
		Long: `上传输入中的单个本地媒体文件。

输入 schema 为 fupload.newbee.wa.media.upload.v1，file 必须是普通文件。dry-run 只校验本地文件。`,
		Example: `  fupload newbee wa media upload --input media.yaml
  Get-Content media.json | fupload newbee wa media upload --input - --output json
  fupload newbee wa media upload --input media.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WAMediaInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.wa.media.upload.v1" || value.File == "" {
				return fmt.Errorf("valid schema and file are required")
			}
			if err := validateLocalFiles([]string{value.File}); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.media.upload", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.UploadWAMedia(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.media.upload", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newWAChangelogCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "changelog",
		Short: "管理 WA 版本日志",
		Long: `读取 WA 最新字符串信息、分页列出版本日志或编辑一条日志。

日志编辑是独立动作，不发布新字符串版本，也不删除历史记录。`,
		Example: `  fupload newbee wa changelog latest --id 123
  fupload newbee wa changelog list --id 123 --output json
  fupload newbee wa changelog edit --input wa-log.yaml`,
	}
	cmd.AddCommand(a.newWAChangelogReadCommand("latest"), a.newWAChangelogReadCommand("get"), a.newWAChangelogListCommand(), a.newWAChangelogEditCommand())
	return cmd
}

func (a *app) newWAChangelogReadCommand(name string) *cobra.Command {
	var id int
	short := "读取 WA 最新字符串版本信息"
	long := `按 WA ID 调用 latest_str_info，返回最新字符串版本及日志信息。

该命令只读；get 是 latest 的语义别名，均不返回登录凭据。`
	cmd := &cobra.Command{
		Use: name, Short: short, Long: long,
		Example: fmt.Sprintf("  fupload newbee wa changelog %s --id 123\n  fupload newbee wa changelog %s --id 123 --output json", name, name),
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.LatestWAVersion(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.changelog."+name, data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "WA ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newWAChangelogListCommand() *cobra.Command {
	var id, page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "分页列出 WA 版本日志",
		Long: `按 WA ID 分页列出字符串版本历史和日志记录 ID。

该命令只读；记录 ID 用于 changelog edit。`,
		Example: `  fupload newbee wa changelog list --id 123
  fupload newbee wa changelog list --id 123 --page 1 --page-size 50 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWAChangelog(cmd.Context(), id, platform.ListOptions{Page: page, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.changelog.list", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "WA ID（必填）")
	cmd.Flags().IntVar(&page, "page", 1, "页码，从 1 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 20, "每页数量，最大 100")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newWAChangelogEditCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "edit",
		Short: "编辑一条 WA 版本日志",
		Long: `按日志记录 ID 编辑 wa_log，不发布新字符串版本。

输入 schema 为 fupload.newbee.wa.changelog.edit.v1；id 必填，changelog 可以为空以清空日志。`,
		Example: `  fupload newbee wa changelog edit --input wa-log.yaml
  Get-Content wa-log.json | fupload newbee wa changelog edit --input - --output json
  fupload newbee wa changelog edit --input wa-log.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WAChangelogEditInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.wa.changelog.edit.v1" || value.ID <= 0 || value.Changelog == nil {
				return fmt.Errorf("valid schema, id, and changelog field are required")
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.changelog.edit", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.EditWAChangelog(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.changelog.edit", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}
