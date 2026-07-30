package skill

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func skillRoot() string {
	return filepath.Join("..", "..", "Release", "fupload")
}

func readSkillFile(t *testing.T, relative string) string {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(skillRoot(), relative))
	if err != nil {
		t.Fatal(err)
	}
	return string(content)
}

func requireText(t *testing.T, text string, values ...string) {
	t.Helper()
	for _, value := range values {
		if !strings.Contains(text, value) {
			t.Errorf("content does not contain %q", value)
		}
	}
}

func TestFuploadSkillRoutesToProgressiveReferences(t *testing.T) {
	root := readSkillFile(t, "SKILL.md")
	requireText(t, root,
		"name: fupload", "references/plugin.md", "references/wa.md", "references/config.md", "references/cli-contract.md",
		".toc", "README", "CHANGELOG", "不使用 Computer Use", "任一步失败立即停止",
	)
	for _, reference := range []string{"references/plugin.md", "references/wa.md", "references/config.md", "references/cli-contract.md"} {
		if info, err := os.Stat(filepath.Join(skillRoot(), reference)); err != nil || info.IsDir() {
			t.Errorf("missing reference %s", reference)
		}
	}
}

func TestWAWorkflowCoversNonDeleteChain(t *testing.T) {
	wa := readSkillFile(t, "references/wa.md")
	requireText(t, wa,
		"wa create", "wa edit", "wa publish-version", "wa changelog", "wa attachment-paths",
		"共创作者", "关联内容", "分享码", "不提供 WA、日志、共创或关联内容的删除命令", "不调用任何草稿接口",
	)
}

func TestPluginWorkflowUsesDynamicOptionsAndConditionalPublic(t *testing.T) {
	plugin := readSkillFile(t, "references/plugin.md")
	requireText(t, plugin,
		"option categories", "option game-versions", "plugin create", "plugin publish-version", "plugin edit",
		"只有用户明确要求公开时", "必须先有版本文件才能公开", "若插件已是公开状态，不做多余编辑", "读回验证",
	)
	if strings.Contains(plugin, "最后固定调用 plugin edit") {
		t.Fatal("plugin workflow contains an unconditional edit")
	}
}

func TestConfigWorkflowRequiresDetailedBackupAndReadback(t *testing.T) {
	config := readSkillFile(t, "references/config.md")
	requireText(t, config,
		"backup list", "backup get --cloud-id", "config create", "config update", "config get",
		"游戏版本由备份决定", "完整 `linked_mods`", "不得沿用旧备份选择", "data=[]",
	)
}

func TestCLIContractPreservesSafetyBoundaries(t *testing.T) {
	contract := readSkillFile(t, "references/cli-contract.md")
	requireText(t, contract,
		"ZIP、哈希、原始 WTF", "每次写后用 list/get 验证", "fupload dd", "不得回退",
	)
}

func TestFuploadOpenAIMetadata(t *testing.T) {
	text := readSkillFile(t, filepath.Join("agents", "openai.yaml"))
	if !strings.Contains(text, `display_name: "Fupload"`) || !strings.Contains(text, `$fupload`) {
		t.Fatalf("openai.yaml does not expose Fupload correctly:\n%s", text)
	}
}
