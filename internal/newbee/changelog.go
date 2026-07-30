package newbee

import (
	"context"
	"encoding/json"
	"fmt"

	"fupload/internal/platform"
)

func (c *Client) ListPluginVersions(ctx context.Context, modID int, options platform.ListOptions) (any, error) {
	if modID <= 0 {
		return nil, fmt.Errorf("mod_id must be greater than zero")
	}
	page, size := normalizePage(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/mod_file/mod_file_list", map[string]any{
		"mod_id": modID, "game_version_id": 0, "pagenum": page, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	return decodePagedList(data, page, size, "plugin versions")
}

func (c *Client) ListPluginChangelog(ctx context.Context, modID int, options platform.ListOptions) (any, error) {
	if modID <= 0 {
		return nil, fmt.Errorf("mod_id must be greater than zero")
	}
	page, size := normalizePage(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/mod_file/changelog_list", map[string]any{
		"mod_id": modID, "pagenum": page, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	return decodePagedList(data, page, size, "plugin changelog list")
}

func (c *Client) GetPluginChangelog(ctx context.Context, fileID int) (any, error) {
	if fileID <= 0 {
		return nil, fmt.Errorf("file_id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/mod_file/get_changelog", map[string]any{"file_id": fileID})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "plugin changelog")
}

func (c *Client) EditPluginChangelog(ctx context.Context, input platform.PluginChangelogEditInput) (any, error) {
	if input.Schema != "fupload.newbee.plugin.changelog.edit.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.plugin.changelog.edit.v1")
	}
	if input.FileID <= 0 {
		return nil, fmt.Errorf("file_id must be greater than zero")
	}
	if input.Changelog == nil {
		return nil, fmt.Errorf("changelog field is required")
	}
	data, err := c.postJSON(ctx, "/creator/wow/mod_file/edit_changelog", map[string]any{
		"file_id": input.FileID, "changelog": *input.Changelog,
	})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "plugin changelog edit")
}

func decodePagedList(data json.RawMessage, page, size int, operation string) (any, error) {
	var payload map[string]any
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("decode %s: %w", operation, err)
	}
	items := mapList(firstValue(payload, "list", "items"))
	return map[string]any{
		"total": intFrom(firstValue(payload, "total", "count")),
		"items": items, "page": page, "page_size": size,
	}, nil
}
