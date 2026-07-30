package newbee

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"fupload/internal/platform"
)

func (c *Client) ListWAs(ctx context.Context, options platform.ListOptions) (any, error) {
	offset, size := normalizeOffset(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/wa/mtg_uc_publish_list", map[string]any{
		"keyword": options.Keyword, "game_version_id": 0, "sort": 3,
		"offset": offset, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	result, err := decodeAny(data, "WA list")
	if err != nil {
		return nil, err
	}
	if object := firstMap(result); object != nil {
		return redactWAStrings(map[string]any{
			"total":  intFrom(firstValue(object, "total", "count")),
			"items":  mapList(firstValue(object, "list", "items")),
			"offset": offset, "page_size": size,
		}), nil
	}
	return redactWAStrings(result), nil
}

func (c *Client) GetWA(ctx context.Context, id int) (any, error) {
	if id <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa/detail_aps", map[string]any{"id": id})
	if err != nil {
		return nil, err
	}
	result, err := decodeAny(data, "WA detail")
	if err != nil {
		return nil, err
	}
	return redactWAStrings(result), nil
}

func (c *Client) ListWACategories(ctx context.Context, gameVersionID int) (any, error) {
	if gameVersionID <= 0 {
		return nil, fmt.Errorf("game_version_id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa/category", map[string]any{"game_version": gameVersionID})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA categories")
}

func (c *Client) ListWAAttachmentPaths(ctx context.Context) (any, error) {
	data, err := c.postJSON(ctx, "/creator/wow/wa/attachment_install_path_list", map[string]any{})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA attachment paths")
}

func (c *Client) UploadWAMedia(ctx context.Context, input platform.WAMediaInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.media.upload.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.wa.media.upload.v1")
	}
	if err := validateFiles([]string{input.File}); err != nil {
		return nil, err
	}
	data, err := c.uploadFile(ctx, "/creator/wow/wa/upload_media", "file", input.File, nil, 2*time.Minute)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA media upload")
}

func (c *Client) CreateWA(ctx context.Context, input platform.WAInput) (any, error) {
	if err := validateWAInput(input, "fupload.newbee.wa.create.v1", false); err != nil {
		return nil, err
	}
	payload, err := c.waPayload(ctx, input, false)
	if err != nil {
		return nil, err
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa/publish", payload)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA create")
}

func (c *Client) EditWA(ctx context.Context, input platform.WAInput) (any, error) {
	if err := validateWAInput(input, "fupload.newbee.wa.edit.v1", true); err != nil {
		return nil, err
	}
	payload, err := c.waPayload(ctx, input, true)
	if err != nil {
		return nil, err
	}
	delete(payload, "wa_str")
	delete(payload, "wa_str_titles")
	delete(payload, "string_mode")
	payload["wa_log"] = ""
	data, err := c.postJSON(ctx, "/creator/wow/wa/update", payload)
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA edit")
}

func (c *Client) PublishWANewVersion(ctx context.Context, input platform.WAInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.publish-version.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.wa.publish-version.v1")
	}
	if input.ID <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	if strings.TrimSpace(input.WAString) == "" {
		return nil, fmt.Errorf("wa_str is required")
	}
	if strings.TrimSpace(input.WAChangelog) == "" {
		return nil, fmt.Errorf("wa_log is required")
	}
	next, err := c.nextWAVersion(ctx, input.ID)
	if err != nil {
		return nil, err
	}
	version := strings.TrimSpace(input.Version)
	if version == "" {
		version = next
	}
	if version == "" {
		return nil, fmt.Errorf("NewBeeBox did not return a next version")
	}
	payload := map[string]any{
		"id": input.ID, "version": version, "wa_log": input.WAChangelog,
		"wa_str": input.WAString, "wa_str_titles": input.WAStringTitles,
		"link_to_channel": input.LinkToChannel,
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa/update_wa_str", payload)
	if err != nil {
		return nil, err
	}
	result, err := decodeAny(data, "WA version publish")
	if err != nil {
		return nil, err
	}
	return map[string]any{"id": input.ID, "version": version, "result": result}, nil
}

func (c *Client) nextWAVersion(ctx context.Context, id int) (string, error) {
	data, err := c.postJSON(ctx, "/creator/wow/wa/get_next_version", map[string]any{"id": id})
	if err != nil {
		return "", err
	}
	var raw any
	if err := json.Unmarshal(data, &raw); err != nil {
		return "", fmt.Errorf("decode WA next version: %w", err)
	}
	if version := stringFrom(raw); version != "" {
		return version, nil
	}
	if object := firstMap(raw); object != nil {
		return firstString(object, "version", "next_version", "t_version"), nil
	}
	return "", nil
}

func (c *Client) LatestWAVersion(ctx context.Context, id int) (any, error) {
	if id <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa_log/latest_str_info", map[string]any{"wa_id": id})
	if err != nil {
		return nil, err
	}
	result, err := decodeAny(data, "WA latest version")
	if err != nil {
		return nil, err
	}
	return redactWAStrings(result), nil
}

func (c *Client) ListWAChangelog(ctx context.Context, id int, options platform.ListOptions) (any, error) {
	if id <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	page, size := normalizePage(options.Page, options.PageSize)
	data, err := c.postJSON(ctx, "/creator/wow/wa_log/list", map[string]any{
		"wa_id": id, "pagenum": page, "pagesize": size,
	})
	if err != nil {
		return nil, err
	}
	result, err := decodePagedList(data, page, size, "WA changelog list")
	if err != nil {
		return nil, err
	}
	return redactWAStrings(result), nil
}

func (c *Client) EditWAChangelog(ctx context.Context, input platform.WAChangelogEditInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.changelog.edit.v1" {
		return nil, fmt.Errorf("schema must be fupload.newbee.wa.changelog.edit.v1")
	}
	if input.ID <= 0 {
		return nil, fmt.Errorf("id must be greater than zero")
	}
	if input.Changelog == nil {
		return nil, fmt.Errorf("changelog field is required")
	}
	data, err := c.postJSON(ctx, "/creator/wow/wa_log/edit", map[string]any{"id": input.ID, "wa_log": *input.Changelog})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA changelog edit")
}

func (c *Client) SearchWACoAuthors(ctx context.Context, keyword string) (any, error) {
	data, err := c.postJSON(ctx, "/creator/co_author/search_user", map[string]any{"keyword": keyword})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA co-author search")
}

func (c *Client) ListWACoAuthors(ctx context.Context, contentID int) (any, error) {
	if contentID <= 0 {
		return nil, fmt.Errorf("content_id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/co_author/list", map[string]any{"content_type": 3, "content_id": contentID})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA co-author list")
}

func (c *Client) SetWACoAuthors(ctx context.Context, input platform.WACoAuthorInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.co-author.set.v1" || input.ContentID <= 0 {
		return nil, fmt.Errorf("valid schema and content_id are required")
	}
	total := 0.0
	for index, author := range input.CoAuthors {
		if author.UserID <= 0 || author.SharePercent <= 0 || author.SharePercent > 1 {
			return nil, fmt.Errorf("co_authors[%d] requires user_id and share_percent in (0,1]", index)
		}
		total += author.SharePercent
	}
	if total > 1.000001 {
		return nil, fmt.Errorf("co_authors share_percent total may not exceed 1")
	}
	data, err := c.postJSON(ctx, "/creator/co_author/set", map[string]any{
		"content_type": 3, "content_id": input.ContentID, "co_authors": input.CoAuthors,
	})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA co-author set")
}

func (c *Client) SearchWAReferences(ctx context.Context, keyword string) (any, error) {
	data, err := c.postJSON(ctx, "/creator/content_reference/search", map[string]any{
		"keyword": keyword, "limit": 20, "target_types": []int{2},
	})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA reference search")
}

func (c *Client) ListWAReferences(ctx context.Context, sourceID int) (any, error) {
	if sourceID <= 0 {
		return nil, fmt.Errorf("source_id must be greater than zero")
	}
	data, err := c.postJSON(ctx, "/creator/content_reference/list", map[string]any{"content_type": 2, "content_id": sourceID})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA reference list")
}

func (c *Client) SetWAReferences(ctx context.Context, input platform.WAReferenceInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.reference.set.v1" || input.SourceID <= 0 {
		return nil, fmt.Errorf("valid schema and source_id are required")
	}
	for index, reference := range input.References {
		if reference.Type <= 0 || reference.ID <= 0 {
			return nil, fmt.Errorf("references[%d] requires positive type and id", index)
		}
	}
	data, err := c.postJSON(ctx, "/creator/content_reference/set", map[string]any{
		"source_type": 2, "source_id": input.SourceID, "references": input.References,
	})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA reference set")
}

func (c *Client) SetWAShareCode(ctx context.Context, input platform.WAShareCodeInput) (any, error) {
	if input.Schema != "fupload.newbee.wa.share-code.set.v1" || input.ModuleID <= 0 {
		return nil, fmt.Errorf("valid schema and module_id are required")
	}
	data, err := c.postJSON(ctx, "/bannerserver/ShareCode/Set", map[string]any{
		"gameId": 1, "moduleId": input.ModuleID, "moduleType": 3,
	})
	if err != nil {
		return nil, err
	}
	return decodeAny(data, "WA share code set")
}

func validateWAInput(input platform.WAInput, schema string, edit bool) error {
	if input.Schema != schema {
		return fmt.Errorf("schema must be %s", schema)
	}
	if edit && input.ID <= 0 {
		return fmt.Errorf("id must be greater than zero")
	}
	if input.GameVersionID <= 0 {
		return fmt.Errorf("game_version_id must be greater than zero")
	}
	if strings.TrimSpace(input.Name) == "" {
		return fmt.Errorf("name is required")
	}
	if len(input.CategoryIDs) == 0 {
		return fmt.Errorf("category_id_list must contain at least one id")
	}
	if strings.TrimSpace(input.Thumbnail) == "" && strings.TrimSpace(input.ThumbnailFile) == "" {
		return fmt.Errorf("thumbnail or thumbnail_file is required")
	}
	if !edit {
		if strings.TrimSpace(input.WAString) == "" || strings.TrimSpace(input.WAChangelog) == "" {
			return fmt.Errorf("wa_str and wa_log are required")
		}
		if input.WAStringMode != "single" && input.WAStringMode != "collection" {
			return fmt.Errorf("string_mode must be single or collection")
		}
		if input.WAStringMode == "collection" && len(input.WAStringTitles) == 0 {
			return fmt.Errorf("wa_str_titles is required for collection mode")
		}
	}
	return validateFiles(append([]string{input.ThumbnailFile}, input.ImageFiles...))
}

func (c *Client) waPayload(ctx context.Context, input platform.WAInput, edit bool) (map[string]any, error) {
	thumbnail, images := input.Thumbnail, append([]string(nil), input.Images...)
	var err error
	if input.ThumbnailFile != "" {
		thumbnail, err = c.uploadWAMediaURL(ctx, input.ThumbnailFile)
		if err != nil {
			return nil, err
		}
	}
	for _, file := range input.ImageFiles {
		url, uploadErr := c.uploadWAMediaURL(ctx, file)
		if uploadErr != nil {
			return nil, uploadErr
		}
		images = append(images, url)
	}
	shareState := 2
	if edit || input.Public != nil && *input.Public {
		shareState = 1
	}
	payload := map[string]any{
		"id": input.ID, "game_version_id": input.GameVersionID, "name": input.Name,
		"intro": input.Intro, "description": input.Description,
		"content_format": defaultInt(input.ContentFormat, 2), "thumbnail": thumbnail,
		"images": images, "category_id_list": input.CategoryIDs,
		"content_origin":       defaultInt(input.ContentOrigin, 1),
		"subscribe_plan_level": input.SubscribePlanLevel, "price": input.Price,
		"time_range": input.TimeRange, "share_state": shareState,
		"link_to_channel": input.LinkToChannel,
		"wa_str":          input.WAString, "wa_str_titles": input.WAStringTitles,
		"wa_log": input.WAChangelog, "string_mode": input.WAStringMode,
		"attachments": input.Attachments,
	}
	if !edit {
		delete(payload, "id")
	}
	return payload, nil
}

func (c *Client) uploadWAMediaURL(ctx context.Context, file string) (string, error) {
	data, err := c.uploadFile(ctx, "/creator/wow/wa/upload_media", "file", file, nil, 2*time.Minute)
	if err != nil {
		return "", err
	}
	return uploadMediaURL(data)
}

func redactWAStrings(value any) any {
	switch current := value.(type) {
	case map[string]any:
		result := make(map[string]any, len(current))
		for key, item := range current {
			lower := strings.ToLower(key)
			if (lower == "wa_str" || lower == "t_wa_str") && stringFrom(item) != "" {
				text := stringFrom(item)
				digest := sha256.Sum256([]byte(text))
				result[key+"_summary"] = map[string]any{"length": len(text), "sha256": fmt.Sprintf("%x", digest)}
				continue
			}
			result[key] = redactWAStrings(item)
		}
		return result
	case []any:
		result := make([]any, len(current))
		for i, item := range current {
			result[i] = redactWAStrings(item)
		}
		return result
	case []map[string]any:
		result := make([]map[string]any, len(current))
		for i, item := range current {
			result[i] = redactWAStrings(item).(map[string]any)
		}
		return result
	default:
		return value
	}
}
