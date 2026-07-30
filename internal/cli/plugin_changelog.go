package cli

import (
	"fmt"

	"fupload/internal/input"
	"fupload/internal/output"
	"fupload/internal/platform"

	"github.com/spf13/cobra"
)

func (a *app) newPluginVersionsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "versions",
		Short: "查询插件版本文件",
		Long: `查询已有插件的版本文件，返回 file_id、版本号、游戏版本及日志摘要。

该资源只读，可用于选择 plugin changelog get/edit 的目标版本。`,
		Example: `  fupload newbee plugin versions list --mod-id 20745
  fupload newbee plugin versions list --mod-id 20745 --page 1 --page-size 20 --output json`,
	}
	cmd.AddCommand(a.newPluginVersionsListCommand())
	return cmd
}

func (a *app) newPluginVersionsListCommand() *cobra.Command {
	var modID, page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出插件版本文件",
		Long: `按插件 ID 分页列出版本文件。

mod-id 必填；page 从 1 开始。该命令不下载压缩包，也不修改版本。`,
		Example: `  fupload newbee plugin versions list --mod-id 20745
  fupload newbee plugin versions list --mod-id 20745 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if modID <= 0 {
				return fmt.Errorf("--mod-id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListPluginVersions(cmd.Context(), modID, platform.ListOptions{Page: page, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "plugin.versions.list", data, false)
		},
	}
	cmd.Flags().IntVar(&modID, "mod-id", 0, "插件 ID（必填）")
	cmd.Flags().IntVar(&page, "page", 1, "页码，从 1 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 20, "每页数量，最大 100")
	_ = cmd.MarkFlagRequired("mod-id")
	return cmd
}

func (a *app) newPluginChangelogCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "changelog",
		Short: "管理插件版本日志",
		Long: `读取或编辑已有插件版本文件的 changelog。

编辑日志是独立动作，不上传新版本、不修改插件资料，也不改变审核状态。`,
		Example: `  fupload newbee plugin changelog list --mod-id 20745
  fupload newbee plugin changelog get --file-id 557441 --output json
  fupload newbee plugin changelog edit --input changelog.yaml`,
	}
	cmd.AddCommand(a.newPluginChangelogListCommand(), a.newPluginChangelogGetCommand(), a.newPluginChangelogEditCommand())
	return cmd
}

func (a *app) newPluginChangelogListCommand() *cobra.Command {
	var modID, page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "分页列出插件版本日志",
		Long: `按插件 ID 列出所有版本的日志摘要和版本文件 ID。

该命令只读；返回的 file_id 用于 get 和 edit。`,
		Example: `  fupload newbee plugin changelog list --mod-id 20745
  fupload newbee plugin changelog list --mod-id 20745 --page-size 50 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if modID <= 0 {
				return fmt.Errorf("--mod-id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListPluginChangelog(cmd.Context(), modID, platform.ListOptions{Page: page, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "plugin.changelog.list", data, false)
		},
	}
	cmd.Flags().IntVar(&modID, "mod-id", 0, "插件 ID（必填）")
	cmd.Flags().IntVar(&page, "page", 1, "页码，从 1 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 20, "每页数量，最大 100")
	_ = cmd.MarkFlagRequired("mod-id")
	return cmd
}

func (a *app) newPluginChangelogGetCommand() *cobra.Command {
	var fileID int
	cmd := &cobra.Command{
		Use:   "get",
		Short: "读取单个插件版本日志",
		Long: `按版本文件 file_id 读取完整 changelog。

该命令只读，不返回插件压缩包或下载地址。`,
		Example: `  fupload newbee plugin changelog get --file-id 557441
  fupload newbee plugin changelog get --file-id 557441 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if fileID <= 0 {
				return fmt.Errorf("--file-id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.GetPluginChangelog(cmd.Context(), fileID)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "plugin.changelog.get", data, false)
		},
	}
	cmd.Flags().IntVar(&fileID, "file-id", 0, "插件版本文件 ID（必填）")
	_ = cmd.MarkFlagRequired("file-id")
	return cmd
}

func (a *app) newPluginChangelogEditCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "edit",
		Short: "编辑单个插件版本日志",
		Long: `编辑已有插件版本文件的 changelog，不上传新版本。

输入 schema 为 fupload.newbee.plugin.changelog.edit.v1，file_id 与 changelog 字段必须存在。
changelog 可以是空字符串，用于清空日志。成功后应使用 get 读回验证。`,
		Example: `  fupload newbee plugin changelog edit --input changelog.yaml
  Get-Content changelog.json | fupload newbee plugin changelog edit --input - --output json
  fupload newbee plugin changelog edit --input changelog.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.PluginChangelogEditInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.plugin.changelog.edit.v1" || value.FileID <= 0 || value.Changelog == nil {
				return fmt.Errorf("valid schema, file_id, and changelog field are required")
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "plugin.changelog.edit", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.EditPluginChangelog(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "plugin.changelog.edit", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}
