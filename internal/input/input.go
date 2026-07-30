package input

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

func Decode(path string, stdin io.Reader, target any) error {
	if strings.TrimSpace(path) == "" {
		return fmt.Errorf("--input is required")
	}
	if path == "-" {
		decoder := newJSONDecoder(stdin)
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(target); err != nil {
			return fmt.Errorf("decode JSON from stdin: %w", err)
		}
		if err := ensureJSONEnd(decoder); err != nil {
			return fmt.Errorf("decode JSON from stdin: %w", err)
		}
		return nil
	}

	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open input %q: %w", path, err)
	}
	defer file.Close()

	switch strings.ToLower(filepath.Ext(path)) {
	case ".json":
		decoder := newJSONDecoder(file)
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(target); err != nil {
			return fmt.Errorf("decode JSON %q: %w", path, err)
		}
		if err := ensureJSONEnd(decoder); err != nil {
			return fmt.Errorf("decode JSON %q: %w", path, err)
		}
		return nil
	case ".yaml", ".yml":
		decoder := yaml.NewDecoder(file)
		decoder.KnownFields(true)
		if err := decoder.Decode(target); err != nil {
			return fmt.Errorf("decode YAML %q: %w", path, err)
		}
		var extra any
		if err := decoder.Decode(&extra); err != io.EOF {
			if err == nil {
				return fmt.Errorf("decode YAML %q: expected one document", path)
			}
			return fmt.Errorf("decode YAML %q: %w", path, err)
		}
		return nil
	default:
		return fmt.Errorf("input %q must use .json, .yaml, or .yml", path)
	}
}

func newJSONDecoder(reader io.Reader) *json.Decoder {
	buffered := bufio.NewReader(reader)
	if prefix, _ := buffered.Peek(3); bytes.Equal(prefix, []byte{0xef, 0xbb, 0xbf}) {
		_, _ = buffered.Discard(3)
	}
	decoder := json.NewDecoder(buffered)
	decoder.DisallowUnknownFields()
	return decoder
}

func ensureJSONEnd(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return fmt.Errorf("expected one document")
		}
		return err
	}
	return nil
}
