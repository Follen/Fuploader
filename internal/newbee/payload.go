package newbee

import (
	"encoding/json"
	"fmt"
	"strconv"

	"fupload/internal/platform"
)

func pluginEditPayload(id int, detail map[string]any) map[string]any {
	return map[string]any{
		"id":                   id,
		"mod_categories":       intSlice(firstValue(detail, "category_ids", "mod_categories")),
		"content_origin":       intFrom(firstValue(detail, "t_original", "content_origin")),
		"content_format":       intFrom(firstValue(detail, "t_content_format", "content_format")),
		"name":                 firstString(detail, "t_name", "name"),
		"description":          firstString(detail, "t_description_v2", "description", "t_description"),
		"intro":                firstString(detail, "t_description", "intro"),
		"logo":                 firstString(detail, "t_logo", "logo"),
		"screenshots":          screenshotURLs(firstValue(detail, "screenshots")),
		"share_state":          1,
		"subscribe_plan_level": intFrom(firstValue(detail, "t_subscribe_plan_level", "subscribe_plan_level")),
		"link_to_channel":      boolFrom(firstValue(detail, "t_link_to_channel", "link_to_channel")),
	}
}

func applyPluginEdit(payload *map[string]any, input platform.PluginEditInput) {
	p := *payload
	if input.Name != nil {
		p["name"] = *input.Name
	}
	if input.Categories != nil {
		p["mod_categories"] = *input.Categories
	}
	if input.ContentOrigin != nil {
		p["content_origin"] = *input.ContentOrigin
	}
	if input.ContentFormat != nil {
		p["content_format"] = *input.ContentFormat
	}
	if input.Intro != nil {
		p["intro"] = *input.Intro
	}
	if input.Description != nil {
		p["description"] = *input.Description
	}
	if input.Logo != nil {
		p["logo"] = *input.Logo
	}
	if input.Screenshots != nil {
		p["screenshots"] = *input.Screenshots
	}
	if input.SubscribePlanLevel != nil {
		p["subscribe_plan_level"] = *input.SubscribePlanLevel
	}
	if input.LinkToChannel != nil {
		p["link_to_channel"] = *input.LinkToChannel
	}
	p["share_state"] = 1
}

func configCreatePayload(input platform.ConfigCreateInput, pictures []string) map[string]any {
	sharing := 0
	if input.Public {
		sharing = 1
	}
	return map[string]any{
		"cloud_id": input.CloudID, "title": input.Title, "content": input.Content,
		"content_format": defaultInt(input.ContentFormat, 2), "intro": input.Intro,
		"pic_url": pictures, "content_origin": defaultInt(input.ContentOrigin, 1),
		"sharing": sharing, "link_to_channel": sharing == 1 && input.LinkToChannel,
		"subscribe_plan_level": input.SubscribePlanLevel, "price": input.Price,
		"time_range": input.TimeRange, "linked_mods": linkedModPayload(input.LinkedMods),
		"ignored_unknown_mods": input.IgnoredUnknownMods, "ignored_materials": input.IgnoredMaterials,
		"ignored_fronts": input.IgnoredFonts, "roleid": input.RoleID,
	}
}

func configUpdatePayload(id int, detail map[string]any) map[string]any {
	return map[string]any{
		"tid":                  id,
		"cloud_id":             intFrom(firstValue(detail, "t_cloudblackid", "cloud_id")),
		"title":                firstString(detail, "t_title", "title"),
		"content":              firstString(detail, "t_content", "content"),
		"content_format":       intFrom(firstValue(detail, "t_content_format", "content_format")),
		"intro":                firstString(detail, "t_intro", "intro"),
		"pic_url":              pictureURLs(detail),
		"content_origin":       intFrom(firstValue(detail, "t_content_origin", "content_origin")),
		"sharing":              1,
		"link_to_channel":      boolFrom(firstValue(detail, "t_link_to_channel", "link_to_channel")),
		"subscribe_plan_level": intFrom(firstValue(detail, "t_subscribe_plan_level", "subscribe_plan_level")),
		"price":                intFrom(firstValue(detail, "t_price", "price")),
		"time_range":           firstString(detail, "t_time_range", "time_range"),
		"linked_mods":          linkedModPayload(linkedModsFromValue(firstValue(detail, "t_linked_mods", "linked_mods"))),
		"ignored_unknown_mods": stringSlice(firstValue(detail, "t_ignored_unknown_mods", "ignored_unknown_mods")),
		"ignored_materials":    stringSlice(firstValue(detail, "t_ignored_materials", "ignored_materials")),
		"ignored_fronts":       stringSlice(firstValue(detail, "t_ignored_fronts", "ignored_fronts")),
		"roleid":               firstString(detail, "t_roleid", "roleid", "role_id"),
	}
}

func applyConfigUpdate(payload map[string]any, input platform.ConfigUpdateInput) {
	if input.CloudID != nil {
		payload["cloud_id"] = *input.CloudID
	}
	if input.Title != nil {
		payload["title"] = *input.Title
	}
	if input.Content != nil {
		payload["content"] = *input.Content
	}
	if input.ContentFormat != nil {
		payload["content_format"] = *input.ContentFormat
	}
	if input.Intro != nil {
		payload["intro"] = *input.Intro
	}
	if input.PictureURLs != nil {
		payload["pic_url"] = *input.PictureURLs
	}
	if input.ContentOrigin != nil {
		payload["content_origin"] = *input.ContentOrigin
	}
	if input.LinkToChannel != nil {
		payload["link_to_channel"] = *input.LinkToChannel
	}
	if input.SubscribePlanLevel != nil {
		payload["subscribe_plan_level"] = *input.SubscribePlanLevel
	}
	if input.Price != nil {
		payload["price"] = *input.Price
	}
	if input.TimeRange != nil {
		payload["time_range"] = *input.TimeRange
	}
	if input.LinkedMods != nil {
		payload["linked_mods"] = linkedModPayload(*input.LinkedMods)
	}
	if input.IgnoredUnknownMods != nil {
		payload["ignored_unknown_mods"] = *input.IgnoredUnknownMods
	}
	if input.IgnoredMaterials != nil {
		payload["ignored_materials"] = *input.IgnoredMaterials
	}
	if input.IgnoredFonts != nil {
		payload["ignored_fronts"] = *input.IgnoredFonts
	}
	if input.RoleID != nil {
		payload["roleid"] = *input.RoleID
	}
	payload["sharing"] = 1
}

func linkedModPayload(mods []platform.LinkedMod) []map[string]any {
	items := make([]map[string]any, 0, len(mods))
	for _, mod := range mods {
		updateType := mod.UpdateType
		if updateType == 0 {
			updateType = 1
		}
		items = append(items, map[string]any{
			"mod_id": mod.ModID, "mod_name": mod.ModName, "mod_file_id": mod.ModFileID,
			"mod_version": nullableString(mod.ModVersion), "display_name": nullableString(mod.DisplayName),
			"updateType": updateType,
		})
	}
	return items
}

func decodeAny(data json.RawMessage, operation string) (any, error) {
	if len(data) == 0 || string(data) == "null" {
		return map[string]any{}, nil
	}
	var result any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode %s response: %w", operation, err)
	}
	return result, nil
}

func normalizePage(page, size int) (int, int) {
	if page <= 0 {
		page = 1
	}
	if size <= 0 {
		size = 50
	}
	if size > 100 {
		size = 100
	}
	return page, size
}

func normalizeOffset(offset, size int) (int, int) {
	if offset < 0 {
		offset = 0
	}
	if size <= 0 {
		size = 50
	}
	if size > 100 {
		size = 100
	}
	return offset, size
}

func firstValue(values map[string]any, keys ...string) any {
	for _, key := range keys {
		if value, ok := values[key]; ok && value != nil {
			return value
		}
	}
	return nil
}

func firstString(values map[string]any, keys ...string) string {
	return stringFrom(firstValue(values, keys...))
}

func stringFrom(value any) string {
	switch v := value.(type) {
	case string:
		return v
	case json.Number:
		return v.String()
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	case int:
		return strconv.Itoa(v)
	default:
		return ""
	}
}

func intFrom(value any) int {
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case json.Number:
		n, _ := v.Int64()
		return int(n)
	case string:
		n, _ := strconv.Atoi(v)
		return n
	default:
		return 0
	}
}

func boolFrom(value any) bool {
	switch v := value.(type) {
	case bool:
		return v
	case float64:
		return v != 0
	case int:
		return v != 0
	case string:
		return v == "1" || v == "true"
	default:
		return false
	}
}

func stringSlice(value any) []string {
	value = decodeMaybeJSON(value)
	items, ok := value.([]any)
	if !ok {
		if strings, ok := value.([]string); ok {
			return append([]string(nil), strings...)
		}
		return []string{}
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		if text := stringFrom(item); text != "" {
			result = append(result, text)
		}
	}
	return result
}

func intSlice(value any) []int {
	value = decodeMaybeJSON(value)
	items, ok := value.([]any)
	if !ok {
		if ints, ok := value.([]int); ok {
			return append([]int(nil), ints...)
		}
		return []int{}
	}
	result := make([]int, 0, len(items))
	for _, item := range items {
		if n := intFrom(item); n != 0 {
			result = append(result, n)
		}
	}
	return result
}

func screenshotURLs(value any) []string {
	value = decodeMaybeJSON(value)
	items, ok := value.([]any)
	if !ok {
		return stringSlice(value)
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		if object, ok := item.(map[string]any); ok {
			if url := firstString(object, "media_url", "url"); url != "" {
				result = append(result, url)
			}
		} else if url := stringFrom(item); url != "" {
			result = append(result, url)
		}
	}
	return result
}

func pictureURLs(detail map[string]any) []string {
	if pictures := stringSlice(firstValue(detail, "pic_url", "picture_urls", "piclist")); len(pictures) > 0 {
		return pictures
	}
	value := firstValue(detail, "piclist")
	items, _ := value.([]any)
	result := []string{}
	for _, item := range items {
		if object, ok := item.(map[string]any); ok {
			if url := firstString(object, "media_url", "url"); url != "" {
				result = append(result, url)
			}
		}
	}
	return result
}

func decodeMaybeJSON(value any) any {
	text, ok := value.(string)
	if !ok || text == "" {
		return value
	}
	var decoded any
	if json.Unmarshal([]byte(text), &decoded) == nil {
		return decoded
	}
	return value
}

func decodeList(value any) any {
	decoded := decodeMaybeJSON(value)
	if decoded == nil {
		return []any{}
	}
	return decoded
}

func flattenMaps(value any) []map[string]any {
	result := []map[string]any{}
	var walk func(any)
	walk = func(current any) {
		switch v := current.(type) {
		case []any:
			for _, item := range v {
				walk(item)
			}
		case map[string]any:
			result = append(result, v)
		}
	}
	walk(value)
	return result
}

func countJSONList(value any) int {
	value = decodeMaybeJSON(value)
	switch v := value.(type) {
	case []any:
		return len(v)
	case []string:
		return len(v)
	default:
		return 0
	}
}

func mapList(value any) []map[string]any {
	value = decodeMaybeJSON(value)
	items, ok := value.([]any)
	if !ok {
		if maps, ok := value.([]map[string]any); ok {
			return append([]map[string]any(nil), maps...)
		}
		return []map[string]any{}
	}
	result := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if object, ok := item.(map[string]any); ok {
			result = append(result, object)
		}
	}
	return result
}

func backupSummary(backup map[string]any) map[string]any {
	return map[string]any{
		"cloud_id": intFrom(backup["t_id"]), "name": backup["t_name"],
		"game_version_id": backup["t_Versionid"], "created_at": backup["t_create_time"],
		"known_plugins":   countJSONList(backup["t_Known_plug"]),
		"unknown_plugins": countJSONList(backup["t_unKnown_list"]),
		"materials":       countJSONList(backup["t_material_list"]),
		"fonts":           countJSONList(backup["t_font_list"]), "accounts": countJSONList(backup["wtflist"]),
	}
}

func safeBackupDetail(backup map[string]any) map[string]any {
	linked := make([]map[string]any, 0)
	for _, mod := range mapList(backup["t_Known_plug"]) {
		linked = append(linked, map[string]any{
			"mod_id": intFrom(mod["id"]), "mod_name": stringFrom(mod["name"]),
			"mod_file_id": nullablePositiveInt(mod["mod_file_id"]), "mod_version": stringFrom(mod["mod_version"]),
			"display_name": stringFrom(mod["display_name"]), "update_type": defaultInt(intFrom(mod["updateType"]), 1),
		})
	}
	roles := make([]map[string]any, 0)
	for _, account := range mapList(backup["wtflist"]) {
		for _, server := range mapList(account["server"]) {
			for _, role := range mapList(server["roleList"]) {
				roles = append(roles, map[string]any{
					"account": stringFrom(account["account"]), "account_id": stringFrom(account["account_id"]),
					"server": stringFrom(server["serverName"]), "name": stringFrom(role["name"]),
					"role_id": stringFrom(role["role_id"]),
				})
			}
		}
	}
	result := backupSummary(backup)
	result["linked_mods"] = linked
	result["unknown_plugins"] = namedItems(backup["t_unKnown_list"])
	result["materials"] = namedItems(backup["t_material_list"])
	result["fonts"] = namedItems(backup["t_font_list"])
	result["roles"] = roles
	delete(result, "accounts")
	return result
}

func safeConfigDetail(detail map[string]any) map[string]any {
	return map[string]any{
		"id":                   intFrom(firstValue(detail, "t_id", "id")),
		"title":                firstString(detail, "t_title", "title"),
		"cloud_id":             intFrom(firstValue(detail, "t_cloudblackid", "cloud_id")),
		"public":               intFrom(firstValue(detail, "t_sharing", "sharing")) != 0,
		"review_status":        firstValue(detail, "t_check", "review_status"),
		"content":              firstString(detail, "t_content", "content"),
		"content_format":       intFrom(firstValue(detail, "t_content_format", "content_format")),
		"intro":                firstString(detail, "t_intro", "intro"),
		"picture_urls":         pictureURLs(detail),
		"content_origin":       intFrom(firstValue(detail, "t_content_origin", "content_origin")),
		"link_to_channel":      boolFrom(firstValue(detail, "t_link_to_channel", "link_to_channel")),
		"subscribe_plan_level": intFrom(firstValue(detail, "t_subscribe_plan_level", "subscribe_plan_level")),
		"price":                intFrom(firstValue(detail, "t_price", "price")),
		"time_range":           firstString(detail, "t_time_range", "time_range"),
		"linked_mods":          linkedModsFromValue(firstValue(detail, "t_linked_mods", "linked_mods")),
		"ignored_unknown_mods": stringSlice(firstValue(detail, "t_ignored_unknown_mods", "ignored_unknown_mods")),
		"ignored_materials":    stringSlice(firstValue(detail, "t_ignored_materials", "ignored_materials")),
		"ignored_fonts":        stringSlice(firstValue(detail, "t_ignored_fronts", "ignored_fonts", "ignored_fronts")),
		"role_id":              firstString(detail, "t_roleid", "roleid", "role_id"),
		"updated_at":           firstValue(detail, "t_update_time", "updated_at"),
	}
}

func linkedModsFromValue(value any) []platform.LinkedMod {
	if mods, ok := value.([]platform.LinkedMod); ok {
		return append([]platform.LinkedMod(nil), mods...)
	}
	items := make([]platform.LinkedMod, 0)
	for _, mod := range mapList(value) {
		var fileID *int
		if n := intFrom(mod["mod_file_id"]); n > 0 {
			fileID = &n
		}
		items = append(items, platform.LinkedMod{
			ModID:       intFrom(firstValue(mod, "mod_id", "id")),
			ModName:     firstString(mod, "mod_name", "name"),
			ModFileID:   fileID,
			ModVersion:  firstString(mod, "mod_version"),
			DisplayName: firstString(mod, "display_name"),
			UpdateType:  defaultInt(intFrom(firstValue(mod, "updateType", "update_type")), 1),
		})
	}
	return items
}

func configID(value any) int {
	if object := firstMap(value); object != nil {
		return intFrom(firstValue(object, "id", "t_id"))
	}
	return 0
}

func namedItems(value any) []string {
	items := make([]string, 0)
	for _, item := range mapList(value) {
		if name := stringFrom(item["name"]); name != "" {
			items = append(items, name)
		}
	}
	return items
}

func nullablePositiveInt(value any) any {
	if n := intFrom(value); n > 0 {
		return n
	}
	return nil
}

func firstMap(value any) map[string]any {
	if object, ok := value.(map[string]any); ok {
		return object
	}
	if list, ok := value.([]any); ok && len(list) > 0 {
		object, _ := list[0].(map[string]any)
		return object
	}
	return nil
}

func defaultInt(value, fallback int) int {
	if value == 0 {
		return fallback
	}
	return value
}
func nullableString(value string) any {
	if value == "" {
		return nil
	}
	return value
}
