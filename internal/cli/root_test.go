package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"fupload/internal/platform"

	"github.com/spf13/cobra"
)

func TestEveryCommandHasDetailedHelpAndExample(t *testing.T) {
	registry := platform.NewRegistry()
	_ = registry.Register("newbee", func() (platform.Service, error) {
		return nil, fmt.Errorf("must not open service while inspecting help")
	})
	root := NewRoot(registry, strings.NewReader(""), &bytes.Buffer{}, &bytes.Buffer{})
	var inspect func(*cobra.Command)
	inspect = func(command *cobra.Command) {
		if strings.TrimSpace(command.Long) == "" {
			t.Errorf("%s has no Long help", command.CommandPath())
		}
		if strings.TrimSpace(command.Example) == "" {
			t.Errorf("%s has no Example", command.CommandPath())
		}
		for _, child := range command.Commands() {
			if child.Name() == "help" || child.Name() == "completion" {
				continue
			}
			inspect(child)
		}
	}
	inspect(root)
}

func TestDryRunDoesNotOpenPlatform(t *testing.T) {
	registry := platform.NewRegistry()
	opened := false
	_ = registry.Register("newbee", func() (platform.Service, error) { opened = true; return nil, fmt.Errorf("unexpected") })
	stdout := &bytes.Buffer{}
	root := NewRoot(registry, strings.NewReader(`{"schema":"fupload.newbee.plugin-edit.v1","id":42}`), stdout, &bytes.Buffer{})
	root.SetArgs([]string{"newbee", "plugin", "edit", "--input", "-", "--dry-run", "--output", "json"})
	root.SetContext(context.Background())
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	if opened {
		t.Fatal("dry-run opened platform service")
	}
	if !strings.Contains(stdout.String(), `"dry_run": true`) {
		t.Fatalf("stdout = %s", stdout.String())
	}
}

func TestUnsupportedDDReturnsStructuredError(t *testing.T) {
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	if code := Execute(context.Background(), []string{"dd", "--output", "json"}, stdout, stderr); code == 0 {
		t.Fatal("Execute(dd) unexpectedly succeeded")
	}
	var envelope struct {
		Platform string `json:"platform"`
		Success  bool   `json:"success"`
		Error    struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(stderr.Bytes(), &envelope); err != nil {
		t.Fatalf("decode error output: %v; output = %s", err, stderr.String())
	}
	if envelope.Platform != platform.DDID || envelope.Success || !strings.Contains(envelope.Error.Message, "not supported") {
		t.Fatalf("unexpected error envelope: %+v", envelope)
	}
}

func TestWADryRunValidatesAndRedactsString(t *testing.T) {
	registry := platform.NewRegistry()
	opened := false
	_ = registry.Register("newbee", func() (platform.Service, error) {
		opened = true
		return nil, fmt.Errorf("unexpected")
	})
	stdout := &bytes.Buffer{}
	root := NewRoot(registry, strings.NewReader(`{"schema":"fupload.newbee.wa.publish-version.v1","id":123,"wa_str":"!WA:2!secret","wa_log":"fix"}`), stdout, &bytes.Buffer{})
	root.SetArgs([]string{"newbee", "wa", "publish-version", "--input", "-", "--dry-run", "--output", "json"})
	root.SetContext(context.Background())
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	if opened {
		t.Fatal("dry-run opened platform service")
	}
	if strings.Contains(stdout.String(), "!WA:2!secret") || !strings.Contains(stdout.String(), "wa_str_summary") {
		t.Fatalf("dry-run did not redact WA string: %s", stdout.String())
	}
}
