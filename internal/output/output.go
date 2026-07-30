package output

import (
	"encoding/json"
	"fmt"
	"io"
)

const Schema = "fupload.output.v1"

type Envelope struct {
	Schema    string `json:"schema"`
	Platform  string `json:"platform,omitempty"`
	Operation string `json:"operation"`
	Success   bool   `json:"success"`
	DryRun    bool   `json:"dry_run,omitempty"`
	Data      any    `json:"data,omitempty"`
	Error     any    `json:"error,omitempty"`
}

func Write(w io.Writer, format, platformID, operation string, data any, dryRun bool) error {
	envelope := Envelope{
		Schema: Schema, Platform: platformID, Operation: operation,
		Success: true, DryRun: dryRun, Data: data,
	}
	if format == "json" {
		encoder := json.NewEncoder(w)
		encoder.SetIndent("", "  ")
		return encoder.Encode(envelope)
	}
	if dryRun {
		fmt.Fprintln(w, "Dry run passed. No remote write was sent.")
	} else {
		fmt.Fprintln(w, "Success.")
	}
	if data != nil {
		encoded, err := json.MarshalIndent(data, "", "  ")
		if err != nil {
			return err
		}
		fmt.Fprintln(w, string(encoded))
	}
	return nil
}

func WriteError(w io.Writer, format, platformID, operation string, err error) {
	if format == "json" {
		_ = json.NewEncoder(w).Encode(Envelope{
			Schema: Schema, Platform: platformID, Operation: operation,
			Success: false, Error: map[string]any{"message": err.Error()},
		})
		return
	}
	fmt.Fprintf(w, "Error: %v\n", err)
}
