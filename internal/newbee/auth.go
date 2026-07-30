package newbee

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gofrs/flock"
)

const (
	defaultAPIBase  = "https://api.newbeebox.com"
	defaultAuthBase = "https://api.next.newbeebox.com/auth"
)

type Session struct {
	AuthorToken   string
	ResourceToken string
}

type SessionProvider interface {
	Session(context.Context) (Session, error)
}

type DesktopAuth struct {
	HTTP     *http.Client
	APIBase  string
	AuthBase string
	AuthDir  string

	mu      sync.Mutex
	cached  Session
	created time.Time
}

type desktopState struct {
	AccessToken  string
	RefreshToken string
	DeviceProof  string
}

func NewDesktopAuth(httpClient *http.Client) (*DesktopAuth, error) {
	appData := os.Getenv("APPDATA")
	if appData == "" {
		return nil, fmt.Errorf("APPDATA is not set; NewBeeBox login state cannot be located")
	}
	authDir := os.Getenv("FUPLOAD_NEWBEE_AUTH_DIR")
	if authDir == "" {
		authDir = filepath.Join(appData, "NewBeeBox", "auth-store")
	}
	apiBase := strings.TrimRight(os.Getenv("FUPLOAD_NEWBEE_API_BASE"), "/")
	if apiBase == "" {
		apiBase = defaultAPIBase
	}
	authBase := strings.TrimRight(os.Getenv("FUPLOAD_NEWBEE_AUTH_BASE"), "/")
	if authBase == "" {
		authBase = defaultAuthBase
	}
	return &DesktopAuth{HTTP: httpClient, APIBase: apiBase, AuthBase: authBase, AuthDir: authDir}, nil
}

func (a *DesktopAuth) Session(ctx context.Context) (Session, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.cached.AuthorToken != "" && time.Since(a.created) < 3*time.Minute {
		return a.cached, nil
	}
	state, err := a.readState()
	if err != nil {
		return Session{}, err
	}
	if !jwtFresh(state.AccessToken, 30*time.Second) {
		state, err = a.refreshWithLock(ctx)
		if err != nil {
			return Session{}, err
		}
	}

	handoff, err := a.post(ctx, a.APIBase+"/v3/user/auth2web", map[string]string{
		"Authorization":   "Bearer " + state.AccessToken,
		"boxversion":      "1.1.17",
		"Accept-Language": "zh-CN",
	}, map[string]any{})
	if err != nil {
		return Session{}, fmt.Errorf("create Creator handoff: %w", err)
	}
	code := stringValue(handoff, "code")
	if code == "" {
		return Session{}, fmt.Errorf("create Creator handoff: response did not contain a code")
	}

	exchange, err := a.post(ctx, a.APIBase+"/v3/user/exchange_web_code", map[string]string{
		"appId": "6", "Accept-Language": "zh-CN",
	}, map[string]any{"code": code})
	if err != nil {
		return Session{}, fmt.Errorf("exchange Creator handoff: %w", err)
	}
	authorToken := stringValue(exchange, "token")
	if authorToken == "" {
		return Session{}, fmt.Errorf("exchange Creator handoff: response did not contain an author token")
	}
	headers := map[string]string{
		"appId": "6", "token": authorToken, "Accept-Language": "zh-CN",
	}
	if initial := stringValue(exchange, "jwtToken"); initial != "" {
		headers["Authorization"] = "Bearer " + initial
	}
	resource, err := a.post(ctx, a.APIBase+"/v3/user/refresh_web_resource_token", headers, map[string]any{})
	if err != nil {
		return Session{}, fmt.Errorf("refresh Creator resource token: %w", err)
	}
	resourceToken := stringValue(resource, "resource_token")
	if resourceToken == "" {
		return Session{}, fmt.Errorf("refresh Creator resource token: response did not contain a resource token")
	}
	a.cached = Session{AuthorToken: authorToken, ResourceToken: resourceToken}
	a.created = time.Now()
	return a.cached, nil
}

func (a *DesktopAuth) refreshWithLock(ctx context.Context) (desktopState, error) {
	if err := os.MkdirAll(a.AuthDir, 0o700); err != nil {
		return desktopState{}, fmt.Errorf("prepare NewBeeBox auth directory: %w", err)
	}
	lock := flock.New(filepath.Join(a.AuthDir, ".fupload-refresh.lock"))
	locked, err := lock.TryLockContext(ctx, 100*time.Millisecond)
	if err != nil {
		return desktopState{}, fmt.Errorf("lock NewBeeBox session refresh: %w", err)
	}
	if !locked {
		return desktopState{}, fmt.Errorf("lock NewBeeBox session refresh: timed out")
	}
	defer lock.Unlock()

	current, err := a.readState()
	if err != nil {
		return desktopState{}, err
	}
	if jwtFresh(current.AccessToken, 30*time.Second) {
		return current, nil
	}
	return a.refresh(ctx, current)
}

func (a *DesktopAuth) readState() (desktopState, error) {
	read := func(name string) (string, error) {
		value, err := os.ReadFile(filepath.Join(a.AuthDir, name))
		if err != nil {
			return "", err
		}
		return strings.TrimSpace(string(value)), nil
	}
	access, err := read("access-token")
	if err != nil {
		return desktopState{}, fmt.Errorf("read NewBeeBox access token: %w", err)
	}
	refresh, err := read("refresh-token")
	if err != nil {
		return desktopState{}, fmt.Errorf("read NewBeeBox refresh token: %w", err)
	}
	proof, _ := read("device-proof")
	return desktopState{AccessToken: access, RefreshToken: refresh, DeviceProof: proof}, nil
}

func (a *DesktopAuth) refresh(ctx context.Context, current desktopState) (desktopState, error) {
	if current.RefreshToken == "" {
		return desktopState{}, fmt.Errorf("NewBeeBox refresh token is missing; sign in with the desktop client first")
	}
	host, _ := os.Hostname()
	form := url.Values{
		"client_id": {"nbb-desktop"}, "grant_type": {"refresh_token"},
		"refresh_token": {current.RefreshToken}, "device_name": {host}, "device_type": {"desktop"},
	}
	if current.DeviceProof != "" {
		form.Set("device_proof", current.DeviceProof)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.AuthBase+"/connect/token", strings.NewReader(form.Encode()))
	if err != nil {
		return desktopState{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := a.HTTP.Do(req)
	if err != nil {
		return desktopState{}, err
	}
	defer resp.Body.Close()
	var payload map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return desktopState{}, fmt.Errorf("decode refresh response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return desktopState{}, fmt.Errorf("refresh NewBeeBox session: HTTP %d: %s", resp.StatusCode, safeMessage(payload))
	}
	next := current
	next.AccessToken = stringValue(payload, "access_token")
	if value := stringValue(payload, "refresh_token"); value != "" {
		next.RefreshToken = value
	}
	if value := stringValue(payload, "device_proof"); value != "" {
		next.DeviceProof = value
	}
	if next.AccessToken == "" {
		return desktopState{}, fmt.Errorf("refresh NewBeeBox session: response did not contain an access token")
	}
	for name, value := range map[string]string{
		"access-token": next.AccessToken, "refresh-token": next.RefreshToken, "device-proof": next.DeviceProof,
	} {
		if value == "" {
			continue
		}
		if err := writeAtomic(filepath.Join(a.AuthDir, name), []byte(value)); err != nil {
			return desktopState{}, fmt.Errorf("persist rotated NewBeeBox credential: %w", err)
		}
	}
	return next, nil
}

func (a *DesktopAuth) post(ctx context.Context, endpoint string, headers map[string]string, body any) (map[string]any, error) {
	encoded, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(string(encoded)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	resp, err := a.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var envelope struct {
		Code    int            `json:"code"`
		Message string         `json:"message"`
		Data    map[string]any `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 || envelope.Code != 1 {
		return nil, fmt.Errorf("HTTP %d, code %d: %s", resp.StatusCode, envelope.Code, envelope.Message)
	}
	return envelope.Data, nil
}

func jwtFresh(token string, leeway time.Duration) bool {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return false
	}
	decoded, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return false
	}
	var claims struct {
		Exp int64 `json:"exp"`
	}
	if json.Unmarshal(decoded, &claims) != nil || claims.Exp == 0 {
		return false
	}
	return time.Unix(claims.Exp, 0).After(time.Now().Add(leeway))
}

func writeAtomic(path string, value []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".fupload-credential-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(value); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return replaceFile(tmpName, path)
}

func stringValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}

func safeMessage(values map[string]any) string {
	for _, key := range []string{"message", "error_description", "error"} {
		if value, ok := values[key].(string); ok && value != "" {
			return redactMessage(value)
		}
	}
	return "request failed"
}
