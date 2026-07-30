package platform

import (
	"strings"
	"testing"
)

func TestRegistryRejectsUnsupportedPlatform(t *testing.T) {
	registry := NewRegistry()
	_, err := registry.Open("dd")
	if err == nil || !strings.Contains(err.Error(), "not supported") {
		t.Fatalf("Open(dd) error = %v", err)
	}
}
