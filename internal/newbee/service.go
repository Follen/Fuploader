package newbee

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"fupload/internal/platform"
)

const maxPluginArchiveSize int64 = 300 * 1024 * 1024

func (c *Client) ListPlugins(ctx context.Context, options platform.ListOptions) (any, error) {
	page, size := normalizePage(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/mod/publish_list", map[string]any{
		"keyword": options.Keyword, "game_version_id": 0,
		"sort_by": "t_last_update", "sort_order": "DESC", "pagenum": page, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	var payload struct {
		Total int              `json:"total"`
		List  []map[string]any `json:"list"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("decode plugin list: %w", err)
	}
	items := make([]map[string]any, 0, len(payload.List))
	for _, item := range payload.List {
		id := intFrom(item["t_id"])
		summary := map[string]any{
			"id": id, "name": item["t_name"], "public": intFrom(item["t_share"]) == 1,
			"review_status": item["t_check"], "latest_version": nil,
		}
		if id > 0 {
			versions, versionErr := c.pluginVersions(ctx, id, 1)
			if versionErr != nil {
				return nil, versionErr
			}
			if len(versions) > 0 {
				summary["latest_version"] = firstString(versions[0], "t_display_name", "display_name", "version", "t_version")
			}
		}
		items = append(items, summary)
	}
	return map[string]any{"total": payload.Total, "items": items, "page": page, "page_size": size}, nil
}

func (c *Client) GetPlugin(ctx context.Context, id int) (any, error) {
	if id <= 0 {
		return nil, fmt.Errorf("plugin id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/mod/publish_detail", map[string]any{"id": id})
	if err != nil {
		return nil, err
	}
	var result any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode plugin detail: %w", err)
	}
	return result, nil
}

func (c *Client) CreatePlugin(ctx context.Context, input platform.PluginCreateInput) (any, error) {
	if err := validatePluginCreate(input); err != nil {
		return nil, err
	}
	if _, err := c.postJSON(ctx, "/creator/wow/mod/permission_check", map[string]any{}); err != nil {
		return nil, fmt.Errorf("plugin permission check: %w", err)
	}
	logo, screenshots, err := c.resolvePluginMedia(ctx, input.Logo, input.LogoFile, input.Screenshots, input.ScreenshotFiles)
	if err != nil {
		return nil, err
	}
	payload := map[string]any{
		"mod_categories": input.Categories, "content_origin": defaultInt(input.ContentOrigin, 1),
		"content_format": defaultInt(input.ContentFormat, 2), "name": input.Name,
		"description": input.Description, "intro": input.Intro, "logo": logo,
		"screenshots": screenshots, "share_state": 0,
		"subscribe_plan_level": input.SubscribePlanLevel, "link_to_channel": false,
	}
	data, err := c.postJSON(ctx, "/creator/wow/mod/create", payload)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "plugin create")
}

func (c *Client) EditPlugin(ctx context.Context, input platform.PluginEditInput) (any, error) {
	if input.Schema != "fupload.newbee.plugin-edit.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.plugin-edit.v1")
	}
	if input.ID <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	if err := validateFiles(append([]string{input.LogoFile}, input.ScreenshotFiles...)); err != nil {
		return nil, err
	}
	detailAny, err := c.GetPlugin(ctx, input.ID)
	if err != nil {
		return nil, err
	}
	detail, ok := detailAny.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("plugin detail has an unexpected shape")
	}
	payload := pluginEditPayload(input.ID, detail)
	applyPluginEdit(&payload, input)
	logo := stringFrom(payload["logo"])
	screenshots := stringSlice(payload["screenshots"])
	if input.LogoFile != "" || len(input.ScreenshotFiles) > 0 {
		logo, screenshots, err = c.resolvePluginMedia(ctx, logo, input.LogoFile, screenshots, input.ScreenshotFiles)
		if err != nil {
			return nil, err
		}
		payload["logo"], payload["screenshots"] = logo, screenshots
	}
	if err := validatePluginPayload(payload); err != nil {
		return nil, err
	}
	data, err := c.postJSON(ctx, "/creator/wow/mod/edit", payload)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "plugin edit")
}

func (c *Client) PublishPluginVersion(ctx context.Context, input platform.PluginVersionInput) (any, error) {
	if err := validatePluginVersion(input); err != nil {
		return nil, err
	}
	versions, err := c.pluginVersions(ctx, input.PluginID, 100)
	if err != nil {
		return nil, err
	}
	for _, version := range versions {
		remote := firstString(version, "t_display_name", "display_name", "version", "t_version")
		if strings.EqualFold(strings.TrimSpace(remote), strings.TrimSpace(input.Version)) {
			return nil, fmt.Errorf("plugin %d already has version %q; refusing to overwrite it", input.PluginID, input.Version)
		}
	}
	gameVersions, _ := json.Marshal(input.GameVersions)
	fields := map[string]string{
		"mod_id": intString(input.PluginID), "version": input.Version,
		"game_version_list": string(gameVersions),
	}
	if input.Changelog != "" {
		fields["changelog"] = input.Changelog
	}
	if input.LinkToChannel != nil {
		fields["link_to_channel"] = fmt.Sprintf("%t", *input.LinkToChannel)
	}
	data, err := c.uploadFile(ctx, "/creator/wow/mod_file/upload_mod_file", "file", input.Archive, fields, 10*time.Minute)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "plugin version upload")
}

func (c *Client) ListBackups(ctx context.Context) (any, error) {
	backups, err := c.listBackupsRaw(ctx)
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0, len(backups))
	for _, backup := range backups {
		items = append(items, backupSummary(backup))
	}
	return map[string]any{"total": len(items), "items": items}, nil
}

func (c *Client) GetBackup(ctx context.Context, cloudID int) (any, error) {
	if cloudID <= 0 {
		return nil, fmt.Errorf("cloud_id must be greater than zero")
	}
	backups, err := c.listBackupsRaw(ctx)
	if err != nil {
		return nil, err
	}
	for _, backup := range backups {
		if intFrom(backup["t_id"]) == cloudID {
			return safeBackupDetail(backup), nil
		}
	}
	return nil, fmt.Errorf("cloud backup %d was not found", cloudID)
}

func (c *Client) ListCategories(ctx context.Context) (any, error) {
	metadata, err := c.metadata(ctx)
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0)
	for _, category := range mapList(metadata["mod_category"]) {
		items = append(items, map[string]any{
			"id": intFrom(category["t_id"]), "name": stringFrom(category["t_name"]),
			"parent_id": intFrom(category["t_parent_category_id"]), "sort_index": intFrom(category["t_show_index"]),
		})
	}
	return map[string]any{"total": len(items), "items": items}, nil
}

func (c *Client) ListGameVersions(ctx context.Context) (any, error) {
	metadata, err := c.metadata(ctx)
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0)
	for _, version := range mapList(metadata["game_version"]) {
		items = append(items, map[string]any{
			"id": intFrom(version["id"]), "name": stringFrom(version["name"]),
			"search_enabled": boolFrom(version["search_enable"]), "versions": stringSlice(version["version"]),
		})
	}
	return map[string]any{"total": len(items), "items": items}, nil
}

func (c *Client) listBackupsRaw(ctx context.Context) ([]map[string]any, error) {
	data, err := c.postJSON(ctx, "/creator/wow/share/list", map[string]any{})
	if err != nil {
		return nil, err
	}
	var raw any
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("decode backup list: %w", err)
	}
	return flattenMaps(raw), nil
}

func (c *Client) metadata(ctx context.Context) (map[string]any, error) {
	url := c.MetadataURL
	if url == "" {
		url = defaultMetadataURL
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("read NewBeeBox metadata: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("read NewBeeBox metadata: HTTP %d", resp.StatusCode)
	}
	var metadata map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&metadata); err != nil {
		return nil, fmt.Errorf("decode NewBeeBox metadata: %w", err)
	}
	return metadata, nil
}

func (c *Client) ListConfigs(ctx context.Context, options platform.ListOptions) (any, error) {
	page, size := normalizeOffset(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/share_config/publish_list", map[string]any{
		"keyword": options.Keyword, "game_version_id": 0, "sort": 3, "offset": page, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	var payload struct {
		Count int              `json:"count"`
		List  []map[string]any `json:"list"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("decode config list: %w", err)
	}
	items := make([]map[string]any, 0, len(payload.List))
	for _, item := range payload.List {
		items = append(items, map[string]any{
			"id": intFrom(item["t_id"]), "title": item["t_title"],
			"cloud_id": item["t_cloudblackid"], "public": intFrom(item["t_sharing"]) != 0,
			"review_status": item["t_check"], "updated_at": item["t_update_time"],
		})
	}
	return map[string]any{"total": payload.Count, "items": items, "offset": page, "page_size": size}, nil
}

func (c *Client) GetConfig(ctx context.Context, id int) (any, error) {
	if id <= 0 {
		return nil, fmt.Errorf("config id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/share_config/details_aps", map[string]any{"id": id})
	if err != nil {
		return nil, err
	}
	raw, err := decodeAny(data, "config detail")
	if err != nil {
		return nil, err
	}
	detail := firstMap(raw)
	if detail == nil {
		return nil, fmt.Errorf("config detail has an unexpected shape")
	}
	return safeConfigDetail(detail), nil
}

func (c *Client) CreateConfig(ctx context.Context, input platform.ConfigCreateInput) (any, error) {
	if err := validateConfigCreate(input); err != nil {
		return nil, err
	}
	pictures, err := c.resolveConfigMedia(ctx, input.PictureURLs, input.PictureFiles)
	if err != nil {
		return nil, err
	}
	payload := configCreatePayload(input, pictures)
	data, err := c.postJSON(ctx, "/creator/wow/share_config/release", payload)
	if err != nil {
		return nil, err
	}
	result, err := decodeAny(data, "config create")
	if err != nil {
		return nil, err
	}
	if configID(result) > 0 {
		return result, nil
	}
	listAny, lookupErr := c.ListConfigs(ctx, platform.ListOptions{PageSize: 100})
	if lookupErr == nil {
		if list, ok := listAny.(map[string]any); ok {
			if items, ok := list["items"].([]map[string]any); ok {
				for _, item := range items {
					if stringFrom(item["title"]) == input.Title && intFrom(item["cloud_id"]) == input.CloudID {
						return map[string]any{"id": intFrom(item["id"]), "title": input.Title, "cloud_id": input.CloudID}, nil
					}
				}
			}
		}
	}
	return result, nil
}

func (c *Client) UpdateConfig(ctx context.Context, input platform.ConfigUpdateInput) (any, error) {
	if input.Schema != "fupload.newbee.config-update.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.config-update.v1")
	}
	if input.ID <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	if input.CloudID != nil && (input.LinkedMods == nil || input.IgnoredUnknownMods == nil || input.IgnoredMaterials == nil || input.IgnoredFonts == nil || input.RoleID == nil) {
		return nil, fmt.Errorf("changing cloud_id requires linked_mods, ignored_unknown_mods, ignored_materials, ignored_fonts, and role_id")
	}
	if err := validateFiles(input.PictureFiles); err != nil {
		return nil, err
	}
	detailAny, err := c.GetConfig(ctx, input.ID)
	if err != nil {
		return nil, err
	}
	detail := firstMap(detailAny)
	if detail == nil {
		return nil, fmt.Errorf("config detail has an unexpected shape")
	}
	payload := configUpdatePayload(input.ID, detail)
	applyConfigUpdate(payload, input)
	pictures := stringSlice(payload["pic_url"])
	if len(input.PictureFiles) > 0 {
		pictures, err = c.resolveConfigMedia(ctx, pictures, input.PictureFiles)
		if err != nil {
			return nil, err
		}
		payload["pic_url"] = pictures
	}
	payload["sharing"] = 1
	if err := validateConfigPayload(payload); err != nil {
		return nil, err
	}
	data, err := c.postJSON(ctx, "/creator/wow/share_config/update", payload)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "config update")
}

func (c *Client) pluginVersions(ctx context.Context, pluginID, size int) ([]map[string]any, error) {
	data, err := c.postJSON(ctx, "/creator/wow/mod_file/mod_file_list", map[string]any{
		"mod_id": pluginID, "game_version_id": 0, "pagenum": 1, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	var payload struct {
		List []map[string]any `json:"list"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("decode plugin versions: %w", err)
	}
	return payload.List, nil
}

func (c *Client) resolvePluginMedia(ctx context.Context, logo, logoFile string, screenshots, files []string) (string, []string, error) {
	if logoFile != "" {
		data, err := c.uploadFile(ctx, "/creator/wow/mod/upload_media", "file", logoFile, nil, 2*time.Minute)
		if err != nil {
			return "", nil, err
		}
		logo, err = uploadMediaURL(data)
		if err != nil {
			return "", nil, err
		}
	}
	for _, file := range files {
		data, err := c.uploadFile(ctx, "/creator/wow/mod/upload_media", "file", file, nil, 2*time.Minute)
		if err != nil {
			return "", nil, err
		}
		url, err := uploadMediaURL(data)
		if err != nil {
			return "", nil, err
		}
		screenshots = append(screenshots, url)
	}
	return logo, screenshots, nil
}

func (c *Client) resolveConfigMedia(ctx context.Context, urls, files []string) ([]string, error) {
	for _, file := range files {
		data, err := c.uploadFile(ctx, "/creator/wow/share_config/upload", "file", file, nil, 2*time.Minute)
		if err != nil {
			return nil, err
		}
		url, err := uploadMediaURL(data)
		if err != nil {
			return nil, err
		}
		urls = append(urls, url)
	}
	return urls, nil
}

func validatePluginCreate(input platform.PluginCreateInput) error {
	if input.Schema != "fupload.newbee.plugin-create.v1" {
		return fmt.Errorf("schema must be fupload.newbee.plugin-create.v1")
	}
	if strings.TrimSpace(input.Name) == "" {
		return fmt.Errorf("name is required")
	}
	if len(input.Categories) == 0 {
		return fmt.Errorf("categories must contain at least one id")
	}
	if len(input.Categories) > 5 {
		return fmt.Errorf("categories may contain at most five ids")
	}
	if strings.TrimSpace(input.Intro) == "" {
		return fmt.Errorf("intro is required")
	}
	if strings.TrimSpace(input.Description) == "" {
		return fmt.Errorf("description is required")
	}
	if input.Logo == "" && input.LogoFile == "" {
		return fmt.Errorf("logo or logo_file is required")
	}
	return validateFiles(append([]string{input.LogoFile}, input.ScreenshotFiles...))
}

func validatePluginVersion(input platform.PluginVersionInput) error {
	if input.Schema != "fupload.newbee.plugin-version.v1" {
		return fmt.Errorf("schema must be fupload.newbee.plugin-version.v1")
	}
	if input.PluginID <= 0 {
		return fmt.Errorf("plugin_id must be greater than zero")
	}
	if strings.TrimSpace(input.Version) == "" {
		return fmt.Errorf("version is required")
	}
	if len(input.GameVersions) == 0 {
		return fmt.Errorf("game_versions must contain at least one id")
	}
	info, err := os.Stat(input.Archive)
	if err != nil {
		return fmt.Errorf("archive: %w", err)
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("archive must be a regular file")
	}
	ext := strings.ToLower(filepath.Ext(input.Archive))
	if ext != ".zip" && ext != ".rar" && ext != ".7z" {
		return fmt.Errorf("archive must use .zip, .rar, or .7z")
	}
	if info.Size() > maxPluginArchiveSize {
		return fmt.Errorf("archive exceeds 300 MB")
	}
	return nil
}

func validateConfigCreate(input platform.ConfigCreateInput) error {
	if input.Schema != "fupload.newbee.config-create.v1" {
		return fmt.Errorf("schema must be fupload.newbee.config-create.v1")
	}
	if input.CloudID <= 0 {
		return fmt.Errorf("cloud_id must be greater than zero")
	}
	if strings.TrimSpace(input.Title) == "" {
		return fmt.Errorf("title is required")
	}
	if strings.TrimSpace(input.Content) == "" {
		return fmt.Errorf("content is required")
	}
	if len(input.PictureURLs) == 0 && len(input.PictureFiles) == 0 {
		return fmt.Errorf("picture_urls or picture_files must contain at least one image")
	}
	return validateFiles(input.PictureFiles)
}

func validateFiles(paths []string) error {
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

func validatePluginPayload(payload map[string]any) error {
	for _, field := range []string{"name", "intro", "description", "logo"} {
		if strings.TrimSpace(stringFrom(payload[field])) == "" {
			return fmt.Errorf("plugin %s is required after merging current detail", field)
		}
	}
	if len(intSlice(payload["mod_categories"])) == 0 {
		return fmt.Errorf("plugin categories are required after merging current detail")
	}
	return nil
}

func validateConfigPayload(payload map[string]any) error {
	if intFrom(payload["cloud_id"]) <= 0 {
		return fmt.Errorf("cloud_id is required after merging current detail")
	}
	if strings.TrimSpace(stringFrom(payload["title"])) == "" {
		return fmt.Errorf("title is required after merging current detail")
	}
	if strings.TrimSpace(stringFrom(payload["content"])) == "" {
		return fmt.Errorf("content is required after merging current detail")
	}
	return nil
}
