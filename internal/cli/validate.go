package cli

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"fupload/internal/platform"
)

func validatePluginCreateLocal(value platform.PluginCreateInput) error {
	if value.Schema != "fupload.newbee.plugin-create.v1" {
		return fmt.Errorf("schema must be fupload.newbee.plugin-create.v1")
	}
	if strings.TrimSpace(value.Name) == "" {
		return fmt.Errorf("name is required")
	}
	if len(value.Categories) == 0 || len(value.Categories) > 5 {
		return fmt.Errorf("categories must contain one to five ids")
	}
	if strings.TrimSpace(value.Intro) == "" {
		return fmt.Errorf("intro is required")
	}
	if strings.TrimSpace(value.Description) == "" {
		return fmt.Errorf("description is required")
	}
	if value.Logo == "" && value.LogoFile == "" {
		return fmt.Errorf("logo or logo_file is required")
	}
	return validateLocalFiles(append([]string{value.LogoFile}, value.ScreenshotFiles...))
}

func validatePluginEditLocal(value platform.PluginEditInput) error {
	if value.Schema != "fupload.newbee.plugin-edit.v1" {
		return fmt.Errorf("schema must be fupload.newbee.plugin-edit.v1")
	}
	if value.ID <= 0 {
		return fmt.Errorf("id must be greater than zero")
	}
	return validateLocalFiles(append([]string{value.LogoFile}, value.ScreenshotFiles...))
}

func validatePluginVersionLocal(value platform.PluginVersionInput) error {
	if value.Schema != "fupload.newbee.plugin-version.v1" {
		return fmt.Errorf("schema must be fupload.newbee.plugin-version.v1")
	}
	if value.PluginID <= 0 {
		return fmt.Errorf("plugin_id must be greater than zero")
	}
	if strings.TrimSpace(value.Version) == "" {
		return fmt.Errorf("version is required")
	}
	if len(value.GameVersions) == 0 {
		return fmt.Errorf("game_versions must contain at least one id")
	}
	if err := validateLocalFiles([]string{value.Archive}); err != nil {
		return err
	}
	info, _ := os.Stat(value.Archive)
	ext := strings.ToLower(filepath.Ext(value.Archive))
	if ext != ".zip" && ext != ".rar" && ext != ".7z" {
		return fmt.Errorf("archive must use .zip, .rar, or .7z")
	}
	if info.Size() > 300*1024*1024 {
		return fmt.Errorf("archive exceeds 300 MB")
	}
	return nil
}

func validateConfigCreateLocal(value platform.ConfigCreateInput) error {
	if value.Schema != "fupload.newbee.config-create.v1" {
		return fmt.Errorf("schema must be fupload.newbee.config-create.v1")
	}
	if value.CloudID <= 0 {
		return fmt.Errorf("cloud_id must be greater than zero")
	}
	if strings.TrimSpace(value.Title) == "" {
		return fmt.Errorf("title is required")
	}
	if strings.TrimSpace(value.Content) == "" {
		return fmt.Errorf("content is required")
	}
	if len(value.PictureURLs) == 0 && len(value.PictureFiles) == 0 {
		return fmt.Errorf("picture_urls or picture_files must contain at least one image")
	}
	return validateLocalFiles(value.PictureFiles)
}

func validateConfigUpdateLocal(value platform.ConfigUpdateInput) error {
	if value.Schema != "fupload.newbee.config-update.v1" {
		return fmt.Errorf("schema must be fupload.newbee.config-update.v1")
	}
	if value.ID <= 0 {
		return fmt.Errorf("id must be greater than zero")
	}
	if value.CloudID != nil {
		if value.LinkedMods == nil || value.IgnoredUnknownMods == nil || value.IgnoredMaterials == nil || value.IgnoredFonts == nil || value.RoleID == nil {
			return fmt.Errorf("changing cloud_id requires linked_mods, ignored_unknown_mods, ignored_materials, ignored_fonts, and role_id")
		}
	}
	return validateLocalFiles(value.PictureFiles)
}

func validateWAInputLocal(value platform.WAInput) error {
	if err := validateLocalFiles(append([]string{value.ThumbnailFile}, value.ImageFiles...)); err != nil {
		return err
	}
	switch value.Schema {
	case "fupload.newbee.wa.create.v1":
		if value.GameVersionID <= 0 {
			return fmt.Errorf("game_version_id must be greater than zero")
		}
		if strings.TrimSpace(value.Name) == "" {
			return fmt.Errorf("name is required")
		}
		if len(value.CategoryIDs) == 0 {
			return fmt.Errorf("category_id_list must contain at least one id")
		}
		if strings.TrimSpace(value.Thumbnail) == "" && strings.TrimSpace(value.ThumbnailFile) == "" {
			return fmt.Errorf("thumbnail or thumbnail_file is required")
		}
		if strings.TrimSpace(value.WAString) == "" || strings.TrimSpace(value.WAChangelog) == "" {
			return fmt.Errorf("wa_str and wa_log are required")
		}
		if value.WAStringMode != "single" && value.WAStringMode != "collection" {
			return fmt.Errorf("string_mode must be single or collection")
		}
		if value.WAStringMode == "collection" && len(value.WAStringTitles) == 0 {
			return fmt.Errorf("wa_str_titles is required for collection mode")
		}
	case "fupload.newbee.wa.edit.v1":
		if value.ID <= 0 || value.GameVersionID <= 0 || strings.TrimSpace(value.Name) == "" {
			return fmt.Errorf("id, game_version_id, and name are required")
		}
		if len(value.CategoryIDs) == 0 {
			return fmt.Errorf("category_id_list must contain at least one id")
		}
		if strings.TrimSpace(value.Thumbnail) == "" && strings.TrimSpace(value.ThumbnailFile) == "" {
			return fmt.Errorf("thumbnail or thumbnail_file is required")
		}
	case "fupload.newbee.wa.publish-version.v1":
		if value.ID <= 0 || strings.TrimSpace(value.WAString) == "" || strings.TrimSpace(value.WAChangelog) == "" {
			return fmt.Errorf("id, wa_str, and wa_log are required")
		}
	default:
		return fmt.Errorf("unsupported WA input schema %q", value.Schema)
	}
	return nil
}

func validateLocalFiles(paths []string) error {
	for _, path := range paths {
		if path == "" {
			continue
		}
		info, err := os.Stat(path)
		if err != nil {
			return fmt.Errorf("file %q: %w", path, err)
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("file %q must be a regular file", path)
		}
	}
	return nil
}

func dryRunSummary(path string, value any) map[string]any {
	return map[string]any{"input": path, "validated": true, "request": redactDryRunValue(value), "remote_checks": false}
}

func redactDryRunValue(value any) any {
	wa, ok := value.(platform.WAInput)
	if !ok {
		return value
	}
	encoded, err := json.Marshal(wa)
	if err != nil {
		return map[string]any{"redacted": true}
	}
	var result map[string]any
	if json.Unmarshal(encoded, &result) != nil {
		return map[string]any{"redacted": true}
	}
	if text := wa.WAString; text != "" {
		digest := sha256.Sum256([]byte(text))
		delete(result, "wa_str")
		result["wa_str_summary"] = map[string]any{"length": len(text), "sha256": fmt.Sprintf("%x", digest)}
	}
	return result
}
