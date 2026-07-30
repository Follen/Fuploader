package input

import (
	"bytes"
	"strings"
	"testing"
)

type fixture struct {
	Schema string `json:"schema" yaml:"schema"`
	Name   string `json:"name" yaml:"name"`
}

func TestDecodeStdinJSONWithUTF8BOM(t *testing.T) {
	input := append([]byte{0xef, 0xbb, 0xbf}, []byte(`{"schema":"v1","name":"powershell"}`)...)
	var value fixture
	if err := Decode("-", bytes.NewReader(input), &value); err != nil {
		t.Fatalf("Decode() error = %v", err)
	}
	if value.Name != "powershell" {
		t.Fatalf("Name = %q", value.Name)
	}
}

func TestDecodeStdinJSONStrict(t *testing.T) {
	var value fixture
	err := Decode("-", strings.NewReader(`{"schema":"v1","name":"ok"}`), &value)
	if err != nil {
		t.Fatalf("Decode() error = %v", err)
	}
	if value.Name != "ok" {
		t.Fatalf("Name = %q", value.Name)
	}

	err = Decode("-", strings.NewReader(`{"schema":"v1","unknown":true}`), &fixture{})
	if err == nil || !strings.Contains(err.Error(), "unknown") {
		t.Fatalf("expected unknown field error, got %v", err)
	}

	err = Decode("-", strings.NewReader(`{"schema":"v1","name":"one"} {"schema":"v1","name":"two"}`), &fixture{})
	if err == nil || !strings.Contains(err.Error(), "one document") {
		t.Fatalf("expected multiple document error, got %v", err)
	}
}

func TestDecodeRejectsUnsupportedExtension(t *testing.T) {
	err := Decode("input.txt", strings.NewReader(""), &fixture{})
	if err == nil {
		t.Fatal("expected extension error")
	}
}
