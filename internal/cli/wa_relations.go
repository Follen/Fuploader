package cli

import (
	"fmt"

	"fupload/internal/input"
	"fupload/internal/output"
	"fupload/internal/platform"

	"github.com/spf13/cobra"
)

func (a *app) newWACoAuthorCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "co-author",
		Short: "管理 WA 联合作者",
		Long: `搜索、读取或设置 WA 的联合作者关系。

所有请求固定使用新手盒子 WA content_type=3；set 是独立写动作，不修改 WA 元数据。`,
		Example: `  fupload newbee wa co-author search --keyword 用户名
  fupload newbee wa co-author list --id 123 --output json
  fupload newbee wa co-author set --input authors.yaml`,
	}
	cmd.AddCommand(a.newWASearchCommand("co-author", func(service platform.Service, cmd *cobra.Command, keyword string) (any, error) {
		return service.SearchWACoAuthors(cmd.Context(), keyword)
	}), a.newWACoAuthorListCommand(), a.newWACoAuthorSetCommand())
	return cmd
}

func (a *app) newWACoAuthorListCommand() *cobra.Command {
	var id int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出 WA 联合作者",
		Long: `按 WA ID 列出当前联合作者。

该命令只读，固定使用 content_type=3。`,
		Example: `  fupload newbee wa co-author list --id 123
  fupload newbee wa co-author list --id 123 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWACoAuthors(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.co-author.list", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "WA ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newWACoAuthorSetCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "set",
		Short: "设置 WA 联合作者",
		Long: `以完整 co_authors 数组替换 WA 的联合作者关系。

输入 schema 为 fupload.newbee.wa.co-author.set.v1，content_id 必填；每项包含 user_id 和 0 至 1 的 share_percent，空数组表示清空关系，不删除 WA。`,
		Example: `  fupload newbee wa co-author set --input authors.yaml
  Get-Content authors.json | fupload newbee wa co-author set --input - --output json
  fupload newbee wa co-author set --input authors.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WACoAuthorInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.wa.co-author.set.v1" || value.ContentID <= 0 {
				return fmt.Errorf("valid schema and content_id are required")
			}
			total := 0.0
			for index, author := range value.CoAuthors {
				if author.UserID <= 0 || author.SharePercent <= 0 || author.SharePercent > 1 {
					return fmt.Errorf("co_authors[%d] requires user_id and share_percent in (0,1]", index)
				}
				total += author.SharePercent
			}
			if total > 1.000001 {
				return fmt.Errorf("co_authors share_percent total may not exceed 1")
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.co-author.set", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.SetWACoAuthors(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.co-author.set", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newWAReferenceCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "reference",
		Short: "管理 WA 关联内容",
		Long: `搜索、读取或设置 WA 的关联内容。

所有请求固定使用新手盒子 WA source_type=2；set 是独立写动作。`,
		Example: `  fupload newbee wa reference search --keyword 酒仙
  fupload newbee wa reference list --id 123 --output json
  fupload newbee wa reference set --input references.yaml`,
	}
	cmd.AddCommand(a.newWASearchCommand("reference", func(service platform.Service, cmd *cobra.Command, keyword string) (any, error) {
		return service.SearchWAReferences(cmd.Context(), keyword)
	}), a.newWAReferenceListCommand(), a.newWAReferenceSetCommand())
	return cmd
}

type waSearchFunc func(platform.Service, *cobra.Command, string) (any, error)

func (a *app) newWASearchCommand(kind string, search waSearchFunc) *cobra.Command {
	var keyword string
	cmd := &cobra.Command{
		Use:   "search",
		Short: "搜索可关联的" + kind,
		Long: `按关键字搜索可用于当前 WA 附属关系的候选。

该命令只读；Skill 必须展示候选 ID 与名称，不能猜测目标。`,
		Example: fmt.Sprintf("  fupload newbee wa %s search --keyword Demo\n  fupload newbee wa %s search --keyword Demo --output json", kind, kind),
		RunE: func(cmd *cobra.Command, _ []string) error {
			if keyword == "" {
				return fmt.Errorf("--keyword is required")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := search(service, cmd, keyword)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa."+kind+".search", data, false)
		},
	}
	cmd.Flags().StringVar(&keyword, "keyword", "", "搜索关键字（必填）")
	_ = cmd.MarkFlagRequired("keyword")
	return cmd
}

func (a *app) newWAReferenceListCommand() *cobra.Command {
	var id int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "列出 WA 关联内容",
		Long: `按 WA ID 列出当前关联内容。

该命令只读，固定使用 source_type=2。`,
		Example: `  fupload newbee wa reference list --id 123
  fupload newbee wa reference list --id 123 --output json`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if id <= 0 {
				return fmt.Errorf("--id must be greater than zero")
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.ListWAReferences(cmd.Context(), id)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.reference.list", data, false)
		},
	}
	cmd.Flags().IntVar(&id, "id", 0, "WA ID（必填）")
	_ = cmd.MarkFlagRequired("id")
	return cmd
}

func (a *app) newWAReferenceSetCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "set",
		Short: "设置 WA 关联内容",
		Long: `以完整 references 数组替换 WA 的关联内容。

输入 schema 为 fupload.newbee.wa.reference.set.v1，source_id 必填；空数组表示清空关联。`,
		Example: `  fupload newbee wa reference set --input references.yaml
  Get-Content references.json | fupload newbee wa reference set --input - --output json
  fupload newbee wa reference set --input references.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WAReferenceInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.wa.reference.set.v1" || value.SourceID <= 0 {
				return fmt.Errorf("valid schema and source_id are required")
			}
			for index, reference := range value.References {
				if reference.Type <= 0 || reference.ID <= 0 {
					return fmt.Errorf("references[%d] requires positive type and id", index)
				}
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.reference.set", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.SetWAReferences(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.reference.set", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}

func (a *app) newWAShareCodeCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "share-code",
		Short: "管理 WA 分享码",
		Long: `为 WA 设置或刷新新手盒子分享码。

该能力固定 gameId=1、moduleType=3；不会修改 WA 字符串或元数据。`,
		Example: `  fupload newbee wa share-code set --input share-code.yaml
  fupload newbee wa share-code set --input share-code.yaml --dry-run`,
	}
	cmd.AddCommand(a.newWAShareCodeSetCommand())
	return cmd
}

func (a *app) newWAShareCodeSetCommand() *cobra.Command {
	var inputPath string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "set",
		Short: "设置一个 WA 分享码",
		Long: `按 module_id 调用新手盒子 ShareCode/Set。

输入 schema 为 fupload.newbee.wa.share-code.set.v1；module_id 是 WA ID。`,
		Example: `  fupload newbee wa share-code set --input share-code.yaml
  Get-Content share-code.json | fupload newbee wa share-code set --input - --output json
  fupload newbee wa share-code set --input share-code.yaml --dry-run`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var value platform.WAShareCodeInput
			if err := input.Decode(inputPath, a.stdin, &value); err != nil {
				return err
			}
			if value.Schema != "fupload.newbee.wa.share-code.set.v1" || value.ModuleID <= 0 {
				return fmt.Errorf("valid schema and module_id are required")
			}
			if dryRun {
				return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.share-code.set", dryRunSummary(inputPath, value), true)
			}
			service, err := a.service(platform.NewBeeID)
			if err != nil {
				return err
			}
			data, err := service.SetWAShareCode(cmd.Context(), value)
			if err != nil {
				return err
			}
			return output.Write(a.stdout, a.format, platform.NewBeeID, "wa.share-code.set", data, false)
		},
	}
	addWriteFlags(cmd, &inputPath, &dryRun)
	return cmd
}
