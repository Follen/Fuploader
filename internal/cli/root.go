package cli

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"

	"fupload/internal/input"
	"fupload/internal/newbee"
	"fupload/internal/output"
	"fupload/internal/platform"

	"github.com/spf13/cobra"
)

type app struct {
	registry *platform.Registry
	stdin    io.Reader
	stdout   io.Writer
	stderr   io.Writer
	format   string
}

func Execute(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	registry := platform.NewRegistry()
	if err := registry.Register("newbee", func() (platform.Service, error) { return newbee.New() }); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	root := NewRoot(registry, os.Stdin, stdout, stderr)
	root.SetArgs(args)
	root.SetContext(ctx)
	if err := root.Execute(); err != nil {
		format, _ := root.Flags().GetString("output")
		platformID, operation := commandTarget(root, args)
		output.WriteError(stderr, format, platformID, operation, err)
		return 1
	}
	return 0
}

func NewRoot(registry *platform.Registry, stdin io.Reader, stdout, stderr io.Writer) *cobra.Command {
	a := &app{registry: registry, stdin: stdin, stdout: stdout, stderr: stderr, format: "human"}
	root := &cobra.Command{
		Use:   "fupload",
		Short: "由 Agent 驱动的插件与配置发布工具",
		Long: `Fupload 是 Fupload Skill 的原子执行层。

当前只支持新手盒子，平台位于命令路径的第一级。写命令读取严格的
YAML/JSON 输入，合法后立即执行；使用 --dry-run 可只做本地校验。
所有命令都支持 --output json，供 Agent 稳定解析。`,
		Example: `  fupload newbee plugin list
  fupload newbee backup list --output json
  fupload newbee plugin create --input plugin.yaml --dry-run`,
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.SetOut(stdout)
	root.SetErr(stderr)
	root.SetIn(stdin)
	root.CompletionOptions.DisableDefaultCmd = true
	root.PersistentFlags().StringVar(&a.format, "output", "human", "输出格式：human 或 json")
	root.PersistentPreRunE = func(cmd *cobra.Command, _ []string) error {
		if a.format != "human" && a.format != "json" {
			return fmt.Errorf("--output must be human or json")
		}
		return nil
	}
	root.AddCommand(a.newNewBeeCommand(), a.newUnsupportedPlatformCommand(platform.DDID))
	return root
}

func (a *app) newUnsupportedPlatformCommand(platformID string) *cobra.Command {
	return &cobra.Command{
		Use:   platformID,
		Short: "尚未支持的平台入口",
		Long: fmt.Sprintf(`平台 %s 的稳定 ID 已预留，但当前版本尚未实现。

该命令不会回退到新手盒子，也不会执行任何远端请求。后续版本可以在平台注册表中
注册真实 adapter，并在该命令下增加平台业务子命令。`, platformID),
		Example: fmt.Sprintf("  fupload %s --output json", platformID),
		RunE: func(_ *cobra.Command, _ []string) error {
			_, err := a.service(platformID)
			return err
		},
	}
}

func (a *app) newNewBeeCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "newbee",
		Short: "操作新手盒子创作者中心",
		Long: `使用本机 NewBeeBox 桌面客户端的已有登录态访问创作者中心。

本命令不会要求粘贴 token，也不提供验证码登录。请先确保桌面客户端已经登录。
插件、WA、云端备份和配置分享分别位于 plugin、wa、backup 和 config 子命令；
分类与游戏版本位于 option 子命令。`,
		Example: `  fupload newbee plugin list
  fupload newbee wa list --output json
  fupload newbee backup list --output json
  fupload newbee config create --input config.yaml`,
	}
	cmd.AddCommand(a.newPluginCommand(), a.newBackupCommand(), a.newConfigCommand(), a.newOptionCommand(), a.newWACommand())
	return cmd
}

func (a *app) newPluginCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "plugin",
		Short: "管理新手盒子魔兽世界插件",
		Long: `查询、创建和更新新手盒子魔兽世界插件。

create 只创建私有插件元数据，edit 只编辑元数据并设置公开，
publish-version 只上传一个新版本。Fupload Skill 可以在一次确认后编排这些原子命令。`,
		Example: `  fupload newbee plugin list
  fupload newbee plugin get --id 123 --output json
  fupload newbee plugin publish-version --input release.yaml`,
	}
	cmd.AddCommand(a.newPluginListCommand(), a.newPluginGetCommand(), a.newPluginCreateCommand(), a.newPluginEditCommand(), a.newPluginVersionCommand(), a.newPluginVersionsCommand(), a.newPluginChangelogCommand())
	return cmd
}

func (a *app) newPluginListCommand() *cobra.Command {
	var keyword string
	var page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出当前作者的插件",
		Long: `列出当前账号在新手盒子创作者中心发布的插件，并补查每个插件的最新版本。

该命令只读。page 从 1 开始，page-size 最大为 100。JSON 输出包含插件 ID、
名称、公开状态、审核状态和最新版本，可用于后续 edit 或 publish-version。`,
		Example: `  fupload newbee plugin list
  fupload newbee plugin list --keyword Details --page 1 --page-size 50 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.ListPlugins(cmd.Context(), platform.ListOptions{Keyword: keyword, Page: page, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "plugin.list", data, false)
		},
	}
	cmd.Flags().StringVar(&keyword, "keyword", "", "按插件名称过滤")
	cmd.Flags().IntVar(&page, "page", 1, "页码，从 1 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 50, "每页数量，最大 100")
	return cmd
}

func (a *app) newPluginGetCommand() *cobra.Command {
	var id int
	cmd := &cobra.Command{
		Use:   "get",
		Short: "读取一个插件的发布详情",
		Long: `按插件 ID 读取新手盒子发布详情。

该命令只读，返回可编辑元数据。Fupload Skill 在修改说明前使用它取得当前值，
避免未提供的字段被清空。`,
		Example: `  fupload newbee plugin get --id 123
  fupload newbee plugin get --id 123 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.GetPlugin(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "plugin.get", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "插件 ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newPluginCreateCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "create",
		Short: "创建私有插件元数据",
		Long: `创建一个新的新手盒子插件元数据记录，不上传版本，也不提交公开审核。

输入 schema 必须为 fupload.newbee.plugin-create.v1。文件支持 YAML/JSON；
--input - 从标准输入读取 JSON。logo_file 与 screenshot_files 会先上传媒体。
必填字段：name、categories、intro、description，以及 logo 或 logo_file。`,
		Example: `  fupload newbee plugin create --input examples/newbee/plugin-create.yaml
  Get-Content plugin.json | fupload newbee plugin create --input - --output json
  fupload newbee plugin create --input plugin.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.PluginCreateInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if err := validatePluginCreateLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, "newbee", "plugin.create", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.CreatePlugin(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "plugin.create", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newPluginEditCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "edit",
		Short: "编辑插件元数据并设为公开",
		Long: `编辑已有插件的名称、分类、简介、详情、图片、订阅或频道设置。

输入 schema 必须为 fupload.newbee.plugin-edit.v1，id 必填，其余字段为补丁。
命令先读取远端详情，未提供的字段保持原值，然后固定 share_state=1。
这会提交或重新进入公开审核，但不代表审核立即通过，也不会上传插件版本。
插件尚无版本文件时，新手盒子会拒绝公开；请先执行 plugin publish-version。`,
		Example: `  fupload newbee plugin edit --input examples/newbee/plugin-edit.yaml
  fupload newbee plugin edit --input plugin-edit.json --output json
  fupload newbee plugin edit --input plugin-edit.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.PluginEditInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if err := validatePluginEditLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, "newbee", "plugin.edit", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.EditPlugin(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "plugin.edit", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newPluginVersionCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "publish-version",
		Short: "为已有插件上传一个新版本",
		Long: `上传一个插件版本压缩包和 changelog，不修改其他插件元数据。

输入 schema 必须为 fupload.newbee.plugin-version.v1。plugin_id、version、
game_versions 和 archive 必填。game_versions 是 ID 数组，可同时选择正式服、
经典旧世等多个目标；先用 option game-versions 查询当前 ID。压缩包限
.zip/.rar/.7z、最大 300 MB。
命令上传前查询远端版本，同版本已存在时拒绝覆盖。Fupload Skill 上传成功后
会再调用 plugin edit，确保更新工作流最终公开并进入审核。`,
		Example: `  fupload newbee plugin publish-version --input examples/newbee/plugin-version.yaml
  fupload newbee plugin publish-version --input release.json --output json
  fupload newbee plugin publish-version --input release.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.PluginVersionInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if err := validatePluginVersionLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, "newbee", "plugin.publish-version", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.PublishPluginVersion(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "plugin.publish-version", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newBackupCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "backup",
		Short: "查询客户端已上传的配置云端备份",
		Long: `查询可被配置分享引用的新手盒子云端备份。

Fupload 不扫描或上传本地 WoW 配置。请先在 NewBeeBox 客户端完成云端备份，
再使用 list 取得 cloud_id，并把它用于 config create 或 config update。`,
		Example: `  fupload newbee backup list
  fupload newbee backup list --output json`,
	}
	cmd.AddCommand(a.newBackupListCommand(), a.newBackupGetCommand())
	return cmd
}

func (a *app) newBackupGetCommand() *cobra.Command {
	var cloudID int
	cmd := &cobra.Command{
		Use:   "get",
		Short: "读取一个云端备份的安全详情",
		Long: `按 cloud_id 读取配置分享所需的备份详情。

该命令只读。输出包含可直接整理为配置输入的 linked_mods、未知插件、材质、
字体和角色候选；不会输出 ZIP/下载地址、哈希、原始 WTF 内容或登录凭据。`,
		Example: `  fupload newbee backup get --cloud-id 3571309
  fupload newbee backup get --cloud-id 3571309 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if cloudID <= 0 {
				return fmt.Errorf("--cloud-id must be greater than zero")
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.GetBackup(cmd.Context(), cloudID)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "backup.get", data, false)
		},
	}
	cmd.Flags().IntVar(&cloudID, "cloud-id", 0, "客户端云端备份 ID（必填）")
	_ = cmd.MarkFlagRequired("cloud-id")
	return cmd
}

func (a *app) newOptionCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "option",
		Short: "查询发布表单使用的平台选项",
		Long: `从新手盒子公开元数据读取发布表单当前使用的分类和游戏版本。

这些命令只读，供 Agent 选择真实 ID；不要把旧 ID 硬编码到 Skill 或脚本。`,
		Example: `  fupload newbee option categories --output json
  fupload newbee option game-versions --output json`,
	}
	cmd.AddCommand(a.newCategoriesCommand(), a.newGameVersionsCommand())
	return cmd
}

func (a *app) newCategoriesCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "categories",
		Short: "列出插件分类",
		Long: `列出新手盒子当前插件分类的 ID、名称、父分类和排序值。

该命令只读，数据来自新手盒子公开元数据。插件创建和编辑时可选择 1 至 5 个分类 ID。`,
		Example: `  fupload newbee option categories
  fupload newbee option categories --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.ListCategories(cmd.Context())
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "option.categories", data, false)
		},
	}
}

func (a *app) newGameVersionsCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "game-versions",
		Short: "列出游戏版本",
		Long: `列出新手盒子当前游戏版本的 ID、名称、搜索状态和可识别客户端版本号。

该命令只读，数据来自新手盒子公开元数据。发布插件版本时至少选择一个真实 ID。`,
		Example: `  fupload newbee option game-versions
  fupload newbee option game-versions --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.ListGameVersions(cmd.Context())
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "option.game-versions", data, false)
		},
	}
}

func (a *app) newBackupListCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "列出可用于配置分享的云端备份",
		Long: `列出当前账号已经通过 NewBeeBox 客户端上传、且 Creator 可选择的云端备份。

该命令只读。JSON 输出包含 cloud_id、名称、游戏版本、创建时间以及插件、
材质、字体和账户数量摘要。没有结果时请先回到客户端上传配置。`,
		Example: `  fupload newbee backup list
  fupload newbee backup list --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.ListBackups(cmd.Context())
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "backup.list", data, false)
		},
	}
}

func (a *app) newConfigCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config",
		Short: "管理基于云端备份的配置分享",
		Long: `查询、创建和更新新手盒子配置分享。

配置分享必须引用 backup list 返回的已有 cloud_id，不能直接上传本地 ZIP。
create 可以创建私有或公开配置；update 固定设置公开并提交或重新进入审核。`,
		Example: `  fupload newbee config list
  fupload newbee config create --input config.yaml
  fupload newbee config update --input update.yaml --output json`,
	}
	cmd.AddCommand(a.newConfigListCommand(), a.newConfigGetCommand(), a.newConfigCreateCommand(), a.newConfigUpdateCommand())
	return cmd
}

func (a *app) newConfigListCommand() *cobra.Command {
	var keyword string
	var offset, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出当前作者的配置分享",
		Long: `列出当前账号已经发布的配置分享。

该命令只读。offset 从 0 开始，page-size 最大为 100。JSON 输出包含发布 ID、
标题、cloud_id、公开状态和审核状态。`,
		Example: `  fupload newbee config list
  fupload newbee config list --keyword 团本 --offset 0 --page-size 50 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.ListConfigs(cmd.Context(), platform.ListOptions{Keyword: keyword, Page: offset, PageSize: pageSize})
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "config.list", data, false)
		},
	}
	cmd.Flags().StringVar(&keyword, "keyword", "", "按配置标题过滤")
	cmd.Flags().IntVar(&offset, "offset", 0, "分页偏移，从 0 开始")
	cmd.Flags().IntVar(&pageSize, "page-size", 50, "每页数量，最大 100")
	return cmd
}

func (a *app) newConfigGetCommand() *cobra.Command {
	var id int
	cmd := &cobra.Command{
		Use:   "get",
		Short: "读取一个配置分享的详情",
		Long: `按发布记录 ID 读取配置分享详情。

该命令只读。Fupload Skill 在更新配置前使用它取得当前字段和 cloud_id，
确保更新输入未提供的字段保持原值。输出已移除角色 ZIP、哈希、原始 WTF
和其他备份隐私字段。`,
		Example: `  fupload newbee config get --id 456
  fupload newbee config get --id 456 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.GetConfig(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "config.get", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "配置分享发布 ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newConfigCreateCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "create",
		Short: "基于已有云端备份创建配置分享",
		Long: `引用 NewBeeBox 客户端已经上传的 cloud_id 创建配置分享。

输入 schema 必须为 fupload.newbee.config-create.v1。cloud_id、title 和 content 必填。
先用 backup get 取得所选备份的 linked_mods、ignored_* 候选和角色。配置的游戏
版本由该备份决定，不能在发布输入中另行改成正式服或怀旧服。picture_files 会先
上传媒体；public 省略时保持私有，设为 true 时提交公开审核。`,
		Example: `  fupload newbee backup list --output json
  fupload newbee config create --input examples/newbee/config-create.yaml
  fupload newbee config create --input config.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.ConfigCreateInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if err := validateConfigCreateLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, "newbee", "config.create", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.CreateConfig(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "config.create", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newConfigUpdateCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "update",
		Short: "更新配置分享并直接设置公开",
		Long: `更新已有配置分享，并固定 sharing=1 提交或重新进入公开审核。

输入 schema 必须为 fupload.newbee.config-update.v1，id 必填，其余字段为补丁。
命令先读取远端详情并保留未提供字段。更换 cloud_id 时，调用方必须重新提供
与新备份对应的 linked_mods、ignored_* 和 role_id，避免沿用错误关联。`,
		Example: `  fupload newbee config update --input examples/newbee/config-update.yaml
  fupload newbee config update --input update.json --output json
  fupload newbee config update --input update.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.ConfigUpdateInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if err := validateConfigUpdateLocal(value); err != nil {
				return err
			}
			if dryRun {
				return output.Write(a.stdout, a.format, "newbee", "config.update", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service("newbee")
			if err != nil {
				return err
			}
			data, err := service.UpdateConfig(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, "newbee", "config.update", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) service(platformID string) (platform.Service, error) {
	return a.registry.Open(platformID)
}

func addWriteFlags(cmd *cobra.Command, inputPath *string, dryRun *bool) {
	cmd.Flags().StringVar(inputPath, "input", "", "输入文件路径（.yaml/.yml/.json），或 - 表示从标准输入读取 JSON（必填）")
	cmd.Flags().BoolVar(dryRun, "dry-run", false, "只执行本地校验并输出脱敏摘要，不发送远端写请求")
	_ = cmd.MarkFlagRequired("input")
}

func commandTarget(root *cobra.Command, args []string) (string, string) {
	cmd, _, err := root.Find(args)
	if err != nil {
		return "", "command"
	}
	parts := strings.Fields(cmd.CommandPath())
	platformID := ""
	if len(parts) >= 2 {
		platformID = parts[1]
	}
	if len(parts) >= 4 {
		return platformID, parts[2] + "." + parts[3]
	}
	return platformID, "command"
}
