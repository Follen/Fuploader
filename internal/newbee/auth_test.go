package newbee

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func unsignedJWT(expires time.Time) string {
	header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"none"}`))
	payload, _ := json.Marshal(map[string]any{"exp": expires.Unix()})
	return header + "." + base64.RawURLEncoding.EncodeToString(payload) + ".signature"
}

func writeAuthFixture(t *testing.T, dir, access, refresh, proof string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]string{"access-token": access, "refresh-token": refresh, "device-proof": proof} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(value), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDesktopAuthCreatesCreatorSession(t *testing.T) {
	dir := t.TempDir()
	writeAuthFixture(t, dir, unsignedJWT(time.Now().Add(time.Hour)), "refresh-old", "proof-old")
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/v3/user/auth2web":
			if request.Header.Get("Authorization") == "" {
				t.Error("missing desktop authorization")
			}
			respond(t, writer, map[string]any{"code": "one-time"})
		case "/v3/user/exchange_web_code":
			respond(t, writer, map[string]any{"token": "author"})
		case "/v3/user/refresh_web_resource_token":
			if request.Header.Get("token") != "author" {
				t.Error("missing author token")
			}
			respond(t, writer, map[string]any{"resource_token": "resource"})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	}))
	defer server.Close()
	auth := &DesktopAuth{HTTP: server.Client(), APIBase: server.URL, AuthBase: server.URL + "/auth", AuthDir: dir}
	session, err := auth.Session(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if session.AuthorToken != "author" || session.ResourceToken != "resource" {
		t.Fatalf("session = %#v", session)
	}
}

func TestDesktopAuthRefreshPersistsRotatedState(t *testing.T) {
	dir := t.TempDir()
	writeAuthFixture(t, dir, unsignedJWT(time.Now().Add(-time.Hour)), "refresh-old", "proof-old")
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/auth/connect/token":
			if err := request.ParseForm(); err != nil {
				t.Fatal(err)
			}
			if request.Form.Get("refresh_token") != "refresh-old" || request.Form.Get("device_proof") != "proof-old" {
				t.Errorf("refresh form = %#v", request.Form)
			}
			_ = json.NewEncoder(writer).Encode(map[string]any{
				"access_token":  unsignedJWT(time.Now().Add(time.Hour)),
				"refresh_token": "refresh-new", "device_proof": "proof-new",
			})
		case "/v3/user/auth2web":
			respond(t, writer, map[string]any{"code": "code"})
		case "/v3/user/exchange_web_code":
			respond(t, writer, map[string]any{"token": "author"})
		case "/v3/user/refresh_web_resource_token":
			respond(t, writer, map[string]any{"resource_token": "resource"})
		default:
			t.Fatalf("unexpected endpoint %s", request.URL.Path)
		}
	}))
	defer server.Close()
	auth := &DesktopAuth{HTTP: server.Client(), APIBase: server.URL, AuthBase: server.URL + "/auth", AuthDir: dir}
	if _, err := auth.Session(context.Background()); err != nil {
		t.Fatal(err)
	}
	refresh, _ := os.ReadFile(filepath.Join(dir, "refresh-token"))
	proof, _ := os.ReadFile(filepath.Join(dir, "device-proof"))
	if string(refresh) != "refresh-new" || string(proof) != "proof-new" {
		t.Fatalf("rotated state was not persisted")
	}
}
