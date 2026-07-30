package platform

import (
	"context"
	"fmt"
	"io"
	"sort"
	"sync"
)

const (
	NewBeeID = "newbee"
	DDID     = "dd"
)

type ListOptions struct {
	Keyword  string
	Page     int
	PageSize int
}

type PluginCreateInput struct {
	Schema             string   `json:"schema" yaml:"schema"`
	Name               string   `json:"name" yaml:"name"`
	Categories         []int    `json:"categories" yaml:"categories"`
	ContentOrigin      int      `json:"content_origin" yaml:"content_origin"`
	ContentFormat      int      `json:"content_format" yaml:"content_format"`
	Intro              string   `json:"intro" yaml:"intro"`
	Description        string   `json:"description" yaml:"description"`
	Logo               string   `json:"logo,omitempty" yaml:"logo,omitempty"`
	LogoFile           string   `json:"logo_file,omitempty" yaml:"logo_file,omitempty"`
	Screenshots        []string `json:"screenshots,omitempty" yaml:"screenshots,omitempty"`
	ScreenshotFiles    []string `json:"screenshot_files,omitempty" yaml:"screenshot_files,omitempty"`
	SubscribePlanLevel int      `json:"subscribe_plan_level,omitempty" yaml:"subscribe_plan_level,omitempty"`
	LinkToChannel      bool     `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
}

type PluginEditInput struct {
	Schema             string    `json:"schema" yaml:"schema"`
	ID                 int       `json:"id" yaml:"id"`
	Name               *string   `json:"name,omitempty" yaml:"name,omitempty"`
	Categories         *[]int    `json:"categories,omitempty" yaml:"categories,omitempty"`
	ContentOrigin      *int      `json:"content_origin,omitempty" yaml:"content_origin,omitempty"`
	ContentFormat      *int      `json:"content_format,omitempty" yaml:"content_format,omitempty"`
	Intro              *string   `json:"intro,omitempty" yaml:"intro,omitempty"`
	Description        *string   `json:"description,omitempty" yaml:"description,omitempty"`
	Logo               *string   `json:"logo,omitempty" yaml:"logo,omitempty"`
	LogoFile           string    `json:"logo_file,omitempty" yaml:"logo_file,omitempty"`
	Screenshots        *[]string `json:"screenshots,omitempty" yaml:"screenshots,omitempty"`
	ScreenshotFiles    []string  `json:"screenshot_files,omitempty" yaml:"screenshot_files,omitempty"`
	SubscribePlanLevel *int      `json:"subscribe_plan_level,omitempty" yaml:"subscribe_plan_level,omitempty"`
	LinkToChannel      *bool     `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
}

type PluginVersionInput struct {
	Schema        string `json:"schema" yaml:"schema"`
	PluginID      int    `json:"plugin_id" yaml:"plugin_id"`
	Version       string `json:"version" yaml:"version"`
	GameVersions  []int  `json:"game_versions" yaml:"game_versions"`
	Archive       string `json:"archive" yaml:"archive"`
	Changelog     string `json:"changelog,omitempty" yaml:"changelog,omitempty"`
	LinkToChannel *bool  `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
}

type PluginChangelogEditInput struct {
	Schema    string  `json:"schema" yaml:"schema"`
	FileID    int     `json:"file_id" yaml:"file_id"`
	Changelog *string `json:"changelog" yaml:"changelog"`
}

type WAInput struct {
	Schema             string         `json:"schema" yaml:"schema"`
	ID                 int            `json:"id,omitempty" yaml:"id,omitempty"`
	GameVersionID      int            `json:"game_version_id,omitempty" yaml:"game_version_id,omitempty"`
	Name               string         `json:"name,omitempty" yaml:"name,omitempty"`
	Intro              string         `json:"intro,omitempty" yaml:"intro,omitempty"`
	Description        string         `json:"description,omitempty" yaml:"description,omitempty"`
	ContentFormat      int            `json:"content_format,omitempty" yaml:"content_format,omitempty"`
	Thumbnail          string         `json:"thumbnail,omitempty" yaml:"thumbnail,omitempty"`
	ThumbnailFile      string         `json:"thumbnail_file,omitempty" yaml:"thumbnail_file,omitempty"`
	Images             []string       `json:"images,omitempty" yaml:"images,omitempty"`
	ImageFiles         []string       `json:"image_files,omitempty" yaml:"image_files,omitempty"`
	CategoryIDs        []int          `json:"category_id_list,omitempty" yaml:"category_id_list,omitempty"`
	ContentOrigin      int            `json:"content_origin,omitempty" yaml:"content_origin,omitempty"`
	SubscribePlanLevel int            `json:"subscribe_plan_level,omitempty" yaml:"subscribe_plan_level,omitempty"`
	Price              int            `json:"price,omitempty" yaml:"price,omitempty"`
	TimeRange          string         `json:"time_range,omitempty" yaml:"time_range,omitempty"`
	Public             *bool          `json:"public,omitempty" yaml:"public,omitempty"`
	LinkToChannel      bool           `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
	WAString           string         `json:"wa_str,omitempty" yaml:"wa_str,omitempty"`
	WAStringTitles     []string       `json:"wa_str_titles,omitempty" yaml:"wa_str_titles,omitempty"`
	WAStringMode       string         `json:"string_mode,omitempty" yaml:"string_mode,omitempty"`
	WAChangelog        string         `json:"wa_log,omitempty" yaml:"wa_log,omitempty"`
	Attachments        []WAAttachment `json:"attachments,omitempty" yaml:"attachments,omitempty"`
	Version            string         `json:"version,omitempty" yaml:"version,omitempty"`
}

type WAAttachment struct {
	Name         string `json:"name" yaml:"name"`
	InstallType  int    `json:"install_type" yaml:"install_type"`
	InstallPath  string `json:"install_path" yaml:"install_path"`
	Value        string `json:"value" yaml:"value"`
	IsCompressed bool   `json:"is_compressed" yaml:"is_compressed"`
	Timestamp    int64  `json:"timestamp,omitempty" yaml:"timestamp,omitempty"`
}

type WAChangelogEditInput struct {
	Schema    string  `json:"schema" yaml:"schema"`
	ID        int     `json:"id" yaml:"id"`
	Changelog *string `json:"changelog" yaml:"changelog"`
}

type WAMediaInput struct {
	Schema string `json:"schema" yaml:"schema"`
	File   string `json:"file" yaml:"file"`
}

type WACoAuthorInput struct {
	Schema    string       `json:"schema" yaml:"schema"`
	ContentID int          `json:"content_id" yaml:"content_id"`
	CoAuthors []WACoAuthor `json:"co_authors" yaml:"co_authors"`
}

type WACoAuthor struct {
	UserID       int     `json:"user_id" yaml:"user_id"`
	SharePercent float64 `json:"share_percent" yaml:"share_percent"`
}

type WAReferenceInput struct {
	Schema     string        `json:"schema" yaml:"schema"`
	SourceID   int           `json:"source_id" yaml:"source_id"`
	References []WAReference `json:"references" yaml:"references"`
}

type WAReference struct {
	Type int `json:"type" yaml:"type"`
	ID   int `json:"id" yaml:"id"`
}

type WAShareCodeInput struct {
	Schema   string `json:"schema" yaml:"schema"`
	ModuleID int    `json:"module_id" yaml:"module_id"`
}

type LinkedMod struct {
	ModID       int    `json:"mod_id" yaml:"mod_id"`
	ModName     string `json:"mod_name" yaml:"mod_name"`
	ModFileID   *int   `json:"mod_file_id,omitempty" yaml:"mod_file_id,omitempty"`
	ModVersion  string `json:"mod_version,omitempty" yaml:"mod_version,omitempty"`
	DisplayName string `json:"display_name,omitempty" yaml:"display_name,omitempty"`
	UpdateType  int    `json:"update_type,omitempty" yaml:"update_type,omitempty"`
}

type ConfigCreateInput struct {
	Schema             string      `json:"schema" yaml:"schema"`
	CloudID            int         `json:"cloud_id" yaml:"cloud_id"`
	Title              string      `json:"title" yaml:"title"`
	Content            string      `json:"content" yaml:"content"`
	ContentFormat      int         `json:"content_format" yaml:"content_format"`
	Intro              string      `json:"intro" yaml:"intro"`
	PictureURLs        []string    `json:"picture_urls,omitempty" yaml:"picture_urls,omitempty"`
	PictureFiles       []string    `json:"picture_files,omitempty" yaml:"picture_files,omitempty"`
	ContentOrigin      int         `json:"content_origin" yaml:"content_origin"`
	Public             bool        `json:"public,omitempty" yaml:"public,omitempty"`
	LinkToChannel      bool        `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
	SubscribePlanLevel int         `json:"subscribe_plan_level,omitempty" yaml:"subscribe_plan_level,omitempty"`
	Price              int         `json:"price,omitempty" yaml:"price,omitempty"`
	TimeRange          string      `json:"time_range,omitempty" yaml:"time_range,omitempty"`
	LinkedMods         []LinkedMod `json:"linked_mods,omitempty" yaml:"linked_mods,omitempty"`
	IgnoredUnknownMods []string    `json:"ignored_unknown_mods,omitempty" yaml:"ignored_unknown_mods,omitempty"`
	IgnoredMaterials   []string    `json:"ignored_materials,omitempty" yaml:"ignored_materials,omitempty"`
	IgnoredFonts       []string    `json:"ignored_fonts,omitempty" yaml:"ignored_fonts,omitempty"`
	RoleID             string      `json:"role_id,omitempty" yaml:"role_id,omitempty"`
}

type ConfigUpdateInput struct {
	Schema             string       `json:"schema" yaml:"schema"`
	ID                 int          `json:"id" yaml:"id"`
	CloudID            *int         `json:"cloud_id,omitempty" yaml:"cloud_id,omitempty"`
	Title              *string      `json:"title,omitempty" yaml:"title,omitempty"`
	Content            *string      `json:"content,omitempty" yaml:"content,omitempty"`
	ContentFormat      *int         `json:"content_format,omitempty" yaml:"content_format,omitempty"`
	Intro              *string      `json:"intro,omitempty" yaml:"intro,omitempty"`
	PictureURLs        *[]string    `json:"picture_urls,omitempty" yaml:"picture_urls,omitempty"`
	PictureFiles       []string     `json:"picture_files,omitempty" yaml:"picture_files,omitempty"`
	ContentOrigin      *int         `json:"content_origin,omitempty" yaml:"content_origin,omitempty"`
	LinkToChannel      *bool        `json:"link_to_channel,omitempty" yaml:"link_to_channel,omitempty"`
	SubscribePlanLevel *int         `json:"subscribe_plan_level,omitempty" yaml:"subscribe_plan_level,omitempty"`
	Price              *int         `json:"price,omitempty" yaml:"price,omitempty"`
	TimeRange          *string      `json:"time_range,omitempty" yaml:"time_range,omitempty"`
	LinkedMods         *[]LinkedMod `json:"linked_mods,omitempty" yaml:"linked_mods,omitempty"`
	IgnoredUnknownMods *[]string    `json:"ignored_unknown_mods,omitempty" yaml:"ignored_unknown_mods,omitempty"`
	IgnoredMaterials   *[]string    `json:"ignored_materials,omitempty" yaml:"ignored_materials,omitempty"`
	IgnoredFonts       *[]string    `json:"ignored_fonts,omitempty" yaml:"ignored_fonts,omitempty"`
	RoleID             *string      `json:"role_id,omitempty" yaml:"role_id,omitempty"`
}

type Service interface {
	ListPlugins(context.Context, ListOptions) (any, error)
	GetPlugin(context.Context, int) (any, error)
	CreatePlugin(context.Context, PluginCreateInput) (any, error)
	EditPlugin(context.Context, PluginEditInput) (any, error)
	PublishPluginVersion(context.Context, PluginVersionInput) (any, error)
	ListPluginVersions(context.Context, int, ListOptions) (any, error)
	ListPluginChangelog(context.Context, int, ListOptions) (any, error)
	GetPluginChangelog(context.Context, int) (any, error)
	EditPluginChangelog(context.Context, PluginChangelogEditInput) (any, error)
	ListBackups(context.Context) (any, error)
	GetBackup(context.Context, int) (any, error)
	ListCategories(context.Context) (any, error)
	ListGameVersions(context.Context) (any, error)
	ListConfigs(context.Context, ListOptions) (any, error)
	GetConfig(context.Context, int) (any, error)
	CreateConfig(context.Context, ConfigCreateInput) (any, error)
	UpdateConfig(context.Context, ConfigUpdateInput) (any, error)
	ListWAs(context.Context, ListOptions) (any, error)
	GetWA(context.Context, int) (any, error)
	ListWACategories(context.Context, int) (any, error)
	ListWAAttachmentPaths(context.Context) (any, error)
	UploadWAMedia(context.Context, WAMediaInput) (any, error)
	CreateWA(context.Context, WAInput) (any, error)
	EditWA(context.Context, WAInput) (any, error)
	PublishWANewVersion(context.Context, WAInput) (any, error)
	LatestWAVersion(context.Context, int) (any, error)
	ListWAChangelog(context.Context, int, ListOptions) (any, error)
	EditWAChangelog(context.Context, WAChangelogEditInput) (any, error)
	SearchWACoAuthors(context.Context, string) (any, error)
	ListWACoAuthors(context.Context, int) (any, error)
	SetWACoAuthors(context.Context, WACoAuthorInput) (any, error)
	SearchWAReferences(context.Context, string) (any, error)
	ListWAReferences(context.Context, int) (any, error)
	SetWAReferences(context.Context, WAReferenceInput) (any, error)
	SetWAShareCode(context.Context, WAShareCodeInput) (any, error)
}

type Factory func() (Service, error)

type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
}

func NewRegistry() *Registry {
	return &Registry{factories: make(map[string]Factory)}
}

func (r *Registry) Register(id string, factory Factory) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if id == "" || factory == nil {
		return fmt.Errorf("platform id and factory are required")
	}
	if _, exists := r.factories[id]; exists {
		return fmt.Errorf("platform %q is already registered", id)
	}
	r.factories[id] = factory
	return nil
}

func (r *Registry) Open(id string) (Service, error) {
	r.mu.RLock()
	factory, ok := r.factories[id]
	r.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("platform %q is not supported", id)
	}
	return factory()
}

func (r *Registry) IDs() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	ids := make([]string, 0, len(r.factories))
	for id := range r.factories {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

type FileOpener interface {
	Open(string) (io.ReadCloser, error)
}
