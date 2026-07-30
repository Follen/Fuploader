package newbee

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"fupload/internal/platform"
)

type staticSessions struct{}

func (staticSessions) Session(context.Context) (Session, error) {
	return Session{AuthorToken: "author-test", ResourceToken: "resource-test"}, nil
}

func testClient(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return &Client{HTTP: server.Client(), APIBase: server.URL, Sessions: staticSessions{}}
}

func assertCreatorHeaders(t *testing.T, request *http.Request) {
	t.Helper()
	if request.Header.Get("appId") != "6" {
		t.Errorf("appId = %q", request.Header.Get("appId"))
	}
	if request.Header.Get("Authorization") != "Bearer resource-test" {
		t.Errorf("Authorization was not set")
	}
	if request.Header.Get("token") != "author-test" {
		t.Errorf("token was not set")
	}
}

func respond(t *testing.T, writer http.ResponseWriter, data any) {
	t.Helper()
	writer.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(writer).Encode(map[string]any{"code": 1, "data": data}); err != nil {
		t.Fatal(err)
	}
}

func decodeBody(t *testing.T, request *http.Request) map[string]any {
	t.Helper()
	defer request.Body.Close()
	var body map[string]any
	if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	return body
}

func TestListPluginsUsesCreatorEndpointsAndNormalizesVersion(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		assertCreatorHeaders(t, request)
		switch request.URL.Path {
		case "/creator/wow/mod/publish_list":
			respond(t, writer, map[string]any{"total": 1, "list": []any{map[string]any{"t_id": 42, "t_name": "Demo", "t_share": 1, "t_check": 0}}})
		case "/creator/wow/mod_file/mod_file_list":
			body := decodeBody(t, request)
			if body["mod_id"] != float64(42) {
				t.Errorf("mod_id = %#v", body["mod_id"])
			}
			respond(t, writer, map[string]any{"list": []any{map[string]any{"t_display_name": "1.2.3"}}})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	result, err := client.ListPlugins(context.Background(), platform.ListOptions{})
	if err != nil {
		t.Fatal(err)
	}
	items := result.(map[string]any)["items"].([]map[string]any)
	if items[0]["latest_version"] != "1.2.3" {
		t.Fatalf("latest_version = %#v", items[0]["latest_version"])
	}
}

func TestEditPluginMergesDetailAndForcesPublic(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/mod/publish_detail":
			respond(t, writer, map[string]any{"t_name": "Old", "t_description": "Intro", "t_description_v2": "Body", "t_logo": "logo", "category_ids": []int{5}, "t_original": 1, "t_content_format": 2})
		case "/creator/wow/mod/edit":
			body := decodeBody(t, request)
			if body["share_state"] != float64(1) {
				t.Errorf("share_state = %#v", body["share_state"])
			}
			if body["name"] != "New" || body["description"] != "Body" {
				t.Errorf("merged body = %#v", body)
			}
			respond(t, writer, map[string]any{"id": 42})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	name := "New"
	_, err := client.EditPlugin(context.Background(), platform.PluginEditInput{Schema: "fupload.newbee.plugin-edit.v1", ID: 42, Name: &name})
	if err != nil {
		t.Fatal(err)
	}
}

func TestCreatePluginChecksPermissionAndCreatesPrivateMetadata(t *testing.T) {
	var calls []string
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		calls = append(calls, request.URL.Path)
		switch request.URL.Path {
		case "/creator/wow/mod/permission_check":
			respond(t, writer, map[string]any{"allowed": true})
		case "/creator/wow/mod/create":
			body := decodeBody(t, request)
			if body["share_state"] != float64(0) || body["link_to_channel"] != false {
				t.Fatalf("create must remain private: %#v", body)
			}
			if body["name"] != "Demo" || body["logo"] != "media/logo.png" {
				t.Fatalf("create body = %#v", body)
			}
			respond(t, writer, map[string]any{"mod_id": 42})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	_, err := client.CreatePlugin(context.Background(), platform.PluginCreateInput{
		Schema: "fupload.newbee.plugin-create.v1", Name: "Demo", Categories: []int{5},
		Intro: "Intro", Description: "Body", Logo: "media/logo.png",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(calls) != 2 || calls[0] != "/creator/wow/mod/permission_check" {
		t.Fatalf("calls = %#v", calls)
	}
}

func TestPluginMediaUploadUsesImageContentType(t *testing.T) {
	dir := t.TempDir()
	logo := filepath.Join(dir, "logo.png")
	if err := os.WriteFile(logo, []byte("png"), 0o600); err != nil {
		t.Fatal(err)
	}
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/mod/permission_check":
			respond(t, writer, map[string]any{"allowed": true})
		case "/creator/wow/mod/upload_media":
			if err := request.ParseMultipartForm(1 << 20); err != nil {
				t.Fatal(err)
			}
			file, header, err := request.FormFile("file")
			if err != nil {
				t.Fatal(err)
			}
			_ = file.Close()
			if header.Header.Get("Content-Type") != "image/png" {
				t.Fatalf("file content type = %q", header.Header.Get("Content-Type"))
			}
			respond(t, writer, map[string]any{"media_url": "media/logo.png"})
		case "/creator/wow/mod/create":
			respond(t, writer, map[string]any{"mod_id": 42})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	_, err := client.CreatePlugin(context.Background(), platform.PluginCreateInput{
		Schema: "fupload.newbee.plugin-create.v1", Name: "Demo", Categories: []int{5},
		Intro: "Intro", Description: "Body", LogoFile: logo,
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestPublishPluginVersionUsesExpectedMultipartFields(t *testing.T) {
	dir := t.TempDir()
	archive := filepath.Join(dir, "demo.zip")
	if err := os.WriteFile(archive, []byte("zip"), 0o600); err != nil {
		t.Fatal(err)
	}
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/mod_file/mod_file_list":
			respond(t, writer, map[string]any{"list": []any{}})
		case "/creator/wow/mod_file/upload_mod_file":
			if err := request.ParseMultipartForm(1 << 20); err != nil {
				t.Fatal(err)
			}
			if request.FormValue("mod_id") != "42" || request.FormValue("version") != "2.0.0" || request.FormValue("game_version_list") != "[1,2]" {
				t.Errorf("multipart fields = %#v", request.Form)
			}
			file, _, err := request.FormFile("file")
			if err != nil {
				t.Fatal(err)
			}
			file.Close()
			respond(t, writer, map[string]any{"file_id": 99})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	_, err := client.PublishPluginVersion(context.Background(), platform.PluginVersionInput{Schema: "fupload.newbee.plugin-version.v1", PluginID: 42, Version: "2.0.0", GameVersions: []int{1, 2}, Archive: archive})
	if err != nil {
		t.Fatal(err)
	}
}

func TestListBackupsFlattensNestedResponse(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		respond(t, writer, []any{[]any{map[string]any{"t_id": 7, "t_name": "Backup", "t_unKnown_list": `[{"name":"x"}]`, "wtflist": []any{map[string]any{"account": "A"}}}}})
	})
	result, err := client.ListBackups(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	items := result.(map[string]any)["items"].([]map[string]any)
	if len(items) != 1 || items[0]["cloud_id"] != 7 || items[0]["unknown_plugins"] != 1 {
		t.Fatalf("items = %#v", items)
	}
}

func TestGetBackupReturnsConfigCandidatesWithoutPrivateFields(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/creator/wow/share/list" {
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
		respond(t, writer, []any{map[string]any{
			"t_id": 7, "t_name": "Backup", "t_Versionid": 2,
			"t_Known_plug":    `[{"id":"42","name":"Demo","fileName":"DemoFolder","mod_file_id":99,"mod_version":"1.2.3","display_name":"1.2.3","updateType":2,"zip":"secret"}]`,
			"t_unKnown_list":  `[{"name":"Unknown","zip":"secret"}]`,
			"t_material_list": []any{map[string]any{"name": "SharedMedia", "hash": "secret"}},
			"t_font_list":     `[{"name":"Fonts","url":"secret"}]`,
			"wtflist": []any{map[string]any{
				"account": "Account", "account_id": "account-1", "zip": "secret",
				"server": []any{map[string]any{"serverName": "Server", "roleList": []any{map[string]any{"role_id": "role-1", "name": "Role", "zip": "secret"}}}},
			}},
		}})
	})
	result, err := client.GetBackup(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	detail := result.(map[string]any)
	linked := detail["linked_mods"].([]map[string]any)
	if len(linked) != 1 || linked[0]["mod_id"] != 42 || linked[0]["mod_name"] != "Demo" || linked[0]["update_type"] != 2 {
		t.Fatalf("linked_mods = %#v", linked)
	}
	roles := detail["roles"].([]map[string]any)
	if len(roles) != 1 || roles[0]["role_id"] != "role-1" || roles[0]["server"] != "Server" {
		t.Fatalf("roles = %#v", roles)
	}
	encoded, err := json.Marshal(detail)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"secret", "zip", "hash", "url"} {
		if strings.Contains(strings.ToLower(string(encoded)), forbidden) {
			t.Fatalf("safe detail leaked %q: %s", forbidden, encoded)
		}
	}
}

func TestMetadataCommandsReturnStableSmallShapes(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			t.Fatalf("method = %s", request.Method)
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(writer, `{"mod_category":[{"t_id":1019,"t_name":"Combat","t_parent_category_id":1,"t_show_index":99,"t_logo_url":"ignored"}],"game_version":[{"id":2,"name":"Retail","search_enable":true,"version":["12.0.0"],"classes":[{"private":"ignored"}]}]}`)
	}))
	defer server.Close()
	client := &Client{HTTP: server.Client(), MetadataURL: server.URL, Sessions: staticSessions{}}

	categoriesAny, err := client.ListCategories(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	categories := categoriesAny.(map[string]any)["items"].([]map[string]any)
	if len(categories) != 1 || categories[0]["id"] != 1019 || categories[0]["parent_id"] != 1 {
		t.Fatalf("categories = %#v", categories)
	}
	versionsAny, err := client.ListGameVersions(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	versions := versionsAny.(map[string]any)["items"].([]map[string]any)
	if len(versions) != 1 || versions[0]["id"] != 2 || versions[0]["search_enabled"] != true {
		t.Fatalf("versions = %#v", versions)
	}
	encoded, _ := json.Marshal(map[string]any{"categories": categories, "versions": versions})
	if strings.Contains(string(encoded), "ignored") || strings.Contains(string(encoded), "classes") {
		t.Fatalf("metadata output was not normalized: %s", encoded)
	}
}

func TestUpdateConfigPreservesDetailAndForcesPublic(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/share_config/details_aps":
			respond(t, writer, []any{map[string]any{"t_id": 9, "t_cloudblackid": 7, "t_title": "Old", "t_content": "Body", "t_content_format": 2, "t_content_origin": 1}})
		case "/creator/wow/share_config/update":
			body := decodeBody(t, request)
			if body["sharing"] != float64(1) || body["cloud_id"] != float64(7) || body["title"] != "New" {
				t.Fatalf("update body = %#v", body)
			}
			respond(t, writer, map[string]any{"id": 9})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	title := "New"
	_, err := client.UpdateConfig(context.Background(), platform.ConfigUpdateInput{Schema: "fupload.newbee.config-update.v1", ID: 9, Title: &title})
	if err != nil {
		t.Fatal(err)
	}
}

func TestGetConfigReturnsSafeStableDetail(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		respond(t, writer, []any{map[string]any{
			"t_id": 9, "t_cloudblackid": 7, "t_title": "Config", "t_content": "Body", "t_intro": "Intro",
			"t_content_format": 2, "t_content_origin": 1, "t_sharing": 1, "t_check": 1, "t_roleid": 123,
			"piclist":       []any{"https://cdn.example/picture.png"},
			"t_linked_mods": `[{"mod_id":42,"mod_name":"Demo","updateType":2}]`,
			"roleobj":       map[string]any{"zip": "secret.zip", "zip_hash": "secret"},
			"wtflist":       []any{map[string]any{"commonConfig": "secret.zip"}},
		}})
	})
	result, err := client.GetConfig(context.Background(), 9)
	if err != nil {
		t.Fatal(err)
	}
	detail := result.(map[string]any)
	if detail["id"] != 9 || detail["cloud_id"] != 7 || detail["role_id"] != "123" {
		t.Fatalf("detail = %#v", detail)
	}
	mods := detail["linked_mods"].([]platform.LinkedMod)
	if len(mods) != 1 || mods[0].ModID != 42 || mods[0].UpdateType != 2 {
		t.Fatalf("linked_mods = %#v", mods)
	}
	encoded, _ := json.Marshal(detail)
	for _, forbidden := range []string{"secret", "zip", "hash", "wtflist", "roleobj"} {
		if strings.Contains(strings.ToLower(string(encoded)), forbidden) {
			t.Fatalf("safe config detail leaked %q: %s", forbidden, encoded)
		}
	}
}

func TestCreateConfigLooksUpIDWhenReleaseReturnsEmptyData(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/share_config/release":
			respond(t, writer, map[string]any{})
		case "/creator/wow/share_config/publish_list":
			respond(t, writer, map[string]any{"count": 1, "list": []any{map[string]any{"t_id": 9, "t_title": "Config", "t_cloudblackid": 7}}})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	result, err := client.CreateConfig(context.Background(), platform.ConfigCreateInput{
		Schema: "fupload.newbee.config-create.v1", CloudID: 7, Title: "Config", Content: "Body", PictureURLs: []string{"media/picture.png"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.(map[string]any)["id"] != 9 {
		t.Fatalf("result = %#v", result)
	}
}

func TestCreateConfigUsesReleaseAndSelectedCloudBackup(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/creator/wow/share_config/release" {
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
		body := decodeBody(t, request)
		if body["cloud_id"] != float64(7) || body["sharing"] != float64(0) {
			t.Fatalf("release body = %#v", body)
		}
		if _, ok := body["ignored_fronts"]; !ok {
			t.Fatalf("release body does not preserve API field ignored_fronts: %#v", body)
		}
		respond(t, writer, map[string]any{"id": 9})
	})
	_, err := client.CreateConfig(context.Background(), platform.ConfigCreateInput{
		Schema: "fupload.newbee.config-create.v1", CloudID: 7, Title: "Config", Content: "Body", PictureURLs: []string{"media/picture.png"},
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestCreateConfigAcceptsArrayMediaResponse(t *testing.T) {
	dir := t.TempDir()
	picture := filepath.Join(dir, "picture.png")
	if err := os.WriteFile(picture, []byte("png"), 0o600); err != nil {
		t.Fatal(err)
	}
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/share_config/upload":
			if err := request.ParseMultipartForm(1 << 20); err != nil {
				t.Fatal(err)
			}
			file, header, err := request.FormFile("file")
			if err != nil {
				t.Fatal(err)
			}
			_ = file.Close()
			if header.Header.Get("Content-Type") != "image/png" {
				t.Fatalf("file content type = %q", header.Header.Get("Content-Type"))
			}
			respond(t, writer, []any{map[string]any{"name": "media/picture.png"}})
		case "/creator/wow/share_config/release":
			body := decodeBody(t, request)
			pictures := body["pic_url"].([]any)
			if len(pictures) != 1 || pictures[0] != "media/picture.png" {
				t.Fatalf("pic_url = %#v", pictures)
			}
			respond(t, writer, map[string]any{"id": 9})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	_, err := client.CreateConfig(context.Background(), platform.ConfigCreateInput{
		Schema: "fupload.newbee.config-create.v1", CloudID: 7, Title: "Config", Content: "Body", PictureFiles: []string{picture},
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestAPIErrorDoesNotIncludeTokens(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		writer.WriteHeader(http.StatusForbidden)
		_, _ = io.WriteString(writer, `{"code":9,"message":"denied Bearer reflected-secret"}`)
	})
	_, err := client.GetPlugin(context.Background(), 1)
	if err == nil {
		t.Fatal("expected error")
	}
	if strings.Contains(err.Error(), "author-test") || strings.Contains(err.Error(), "resource-test") || strings.Contains(err.Error(), "reflected-secret") {
		t.Fatalf("error leaked token: %v", err)
	}
}

func TestPluginChangelogUsesDedicatedEndpoints(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/mod_file/changelog_list":
			body := decodeBody(t, request)
			if body["mod_id"] != float64(20745) || body["pagenum"] != float64(1) {
				t.Fatalf("list body = %#v", body)
			}
			respond(t, writer, map[string]any{"total": 1, "list": []any{map[string]any{"file_id": 557441, "changelog": "old"}}})
		case "/creator/wow/mod_file/get_changelog":
			body := decodeBody(t, request)
			if body["file_id"] != float64(557441) {
				t.Fatalf("get body = %#v", body)
			}
			respond(t, writer, map[string]any{"file_id": 557441, "changelog": "old"})
		case "/creator/wow/mod_file/edit_changelog":
			body := decodeBody(t, request)
			if body["file_id"] != float64(557441) || body["changelog"] != "new" {
				t.Fatalf("edit body = %#v", body)
			}
			respond(t, writer, map[string]any{"file_id": 557441})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	if _, err := client.ListPluginChangelog(context.Background(), 20745, platform.ListOptions{}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.GetPluginChangelog(context.Background(), 557441); err != nil {
		t.Fatal(err)
	}
	newLog := "new"
	if _, err := client.EditPluginChangelog(context.Background(), platform.PluginChangelogEditInput{Schema: "fupload.newbee.plugin.changelog.edit.v1", FileID: 557441, Changelog: &newLog}); err != nil {
		t.Fatal(err)
	}
}

func TestWACreateAndVersionUseFrontendPayloads(t *testing.T) {
	var calls []string
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		calls = append(calls, request.URL.Path)
		switch request.URL.Path {
		case "/creator/wow/wa/publish":
			body := decodeBody(t, request)
			if body["game_version_id"] != float64(1) || body["name"] != "Demo" || body["share_state"] != float64(2) {
				t.Fatalf("publish body = %#v", body)
			}
			if body["wa_str"] != "!WA:2!demo" || body["string_mode"] != "single" {
				t.Fatalf("string body = %#v", body)
			}
			respond(t, writer, map[string]any{"wa_id": 123})
		case "/creator/wow/wa/get_next_version":
			body := decodeBody(t, request)
			if body["id"] != float64(123) {
				t.Fatalf("next body = %#v", body)
			}
			respond(t, writer, map[string]any{"version": "1.0.1"})
		case "/creator/wow/wa/update_wa_str":
			body := decodeBody(t, request)
			if body["id"] != float64(123) || body["version"] != "1.0.1" || body["wa_log"] != "fix" {
				t.Fatalf("version body = %#v", body)
			}
			respond(t, writer, map[string]any{"id": 123})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	_, err := client.CreateWA(context.Background(), platform.WAInput{
		Schema: "fupload.newbee.wa.create.v1", GameVersionID: 1, Name: "Demo",
		Thumbnail: "media/cover.png", CategoryIDs: []int{88},
		WAString: "!WA:2!demo", WAChangelog: "first", WAStringMode: "single",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.PublishWANewVersion(context.Background(), platform.WAInput{
		Schema: "fupload.newbee.wa.publish-version.v1", ID: 123,
		WAString: "!WA:2!next", WAChangelog: "fix",
	})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(calls, ",") != "/creator/wow/wa/publish,/creator/wow/wa/get_next_version,/creator/wow/wa/update_wa_str" {
		t.Fatalf("calls = %#v", calls)
	}
}

func TestWAReadRedactsRawStringAndRelationsUseFixedTypes(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/creator/wow/wa/detail_aps":
			respond(t, writer, map[string]any{"id": 123, "wa_str": "!WA:2!secret"})
		case "/creator/co_author/set":
			body := decodeBody(t, request)
			if body["content_type"] != float64(3) || body["content_id"] != float64(123) {
				t.Fatalf("co-author body = %#v", body)
			}
			coAuthors := body["co_authors"].([]any)
			if len(coAuthors) != 1 || coAuthors[0].(map[string]any)["share_percent"] != float64(0.25) {
				t.Fatalf("co-authors = %#v", coAuthors)
			}
			respond(t, writer, map[string]any{"ok": true})
		case "/creator/content_reference/set":
			body := decodeBody(t, request)
			if body["source_type"] != float64(2) || body["source_id"] != float64(123) {
				t.Fatalf("reference body = %#v", body)
			}
			respond(t, writer, map[string]any{"ok": true})
		case "/bannerserver/ShareCode/Set":
			body := decodeBody(t, request)
			if body["gameId"] != float64(1) || body["moduleType"] != float64(3) || body["moduleId"] != float64(123) {
				t.Fatalf("share-code body = %#v", body)
			}
			respond(t, writer, map[string]any{"shareCode": "ABC"})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	})
	detail, err := client.GetWA(context.Background(), 123)
	if err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(detail)
	if strings.Contains(string(encoded), "!WA:2!secret") || !strings.Contains(string(encoded), "wa_str_summary") {
		t.Fatalf("detail was not redacted: %s", encoded)
	}
	if _, err := client.SetWACoAuthors(context.Background(), platform.WACoAuthorInput{Schema: "fupload.newbee.wa.co-author.set.v1", ContentID: 123, CoAuthors: []platform.WACoAuthor{{UserID: 9, SharePercent: 0.25}}}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetWAReferences(context.Background(), platform.WAReferenceInput{Schema: "fupload.newbee.wa.reference.set.v1", SourceID: 123, References: []platform.WAReference{{Type: 1, ID: 8}}}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetWAShareCode(context.Background(), platform.WAShareCodeInput{Schema: "fupload.newbee.wa.share-code.set.v1", ModuleID: 123}); err != nil {
		t.Fatal(err)
	}
}

func TestWACategoriesUsesFrontendGameVersionField(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/creator/wow/wa/category" {
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
		body := decodeBody(t, request)
		if body["game_version"] != float64(2) {
			t.Fatalf("category body = %#v", body)
		}
		if _, exists := body["game_version_id"]; exists {
			t.Fatalf("category sent unsupported game_version_id: %#v", body)
		}
		respond(t, writer, []any{map[string]any{"id": 1, "name": "Combat"}})
	})
	if _, err := client.ListWACategories(context.Background(), 2); err != nil {
		t.Fatal(err)
	}
}

func TestWAReferenceReadEndpointsUseTheirDistinctFields(t *testing.T) {
	client := testClient(t, func(writer http.ResponseWriter, request *http.Request) {
		body := decodeBody(t, request)
		switch request.URL.Path {
		case "/creator/content_reference/search":
			if body["keyword"] != "Demo" || body["limit"] != float64(20) {
				t.Fatalf("search body = %#v", body)
			}
			types := body["target_types"].([]any)
			if len(types) != 1 || types[0] != float64(2) {
				t.Fatalf("target_types = %#v", types)
			}
		case "/creator/content_reference/list":
			if body["content_type"] != float64(2) || body["content_id"] != float64(123) {
				t.Fatalf("list body = %#v", body)
			}
			if _, exists := body["source_type"]; exists {
				t.Fatalf("list used set fields: %#v", body)
			}
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
		respond(t, writer, map[string]any{})
	})
	if _, err := client.SearchWAReferences(context.Background(), "Demo"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.ListWAReferences(context.Background(), 123); err != nil {
		t.Fatal(err)
	}
}
