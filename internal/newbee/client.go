package newbee

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Client struct {
	HTTP        *http.Client
	APIBase     string
	MetadataURL string
	Sessions    SessionProvider
}

const defaultMetadataURL = "https://cdn2.newbeebox.com/modconfig.json"

type apiEnvelope struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
}

type APIError struct {
	Endpoint   string
	HTTPStatus int
	Code       int
	Message    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("NewBeeBox %s failed (HTTP %d, code %d): %s", e.Endpoint, e.HTTPStatus, e.Code, e.Message)
}

func New() (*Client, error) {
	httpClient := &http.Client{Timeout: 60 * time.Second}
	auth, err := NewDesktopAuth(httpClient)
	if err != nil {
		return nil, err
	}
	return &Client{HTTP: httpClient, APIBase: auth.APIBase, MetadataURL: defaultMetadataURL, Sessions: auth}, nil
}

func (c *Client) postJSON(ctx context.Context, endpoint string, body any) (json.RawMessage, error) {
	session, err := c.Sessions.Session(ctx)
	if err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(c.APIBase, "/")+endpoint, bytes.NewReader(encoded))
	if err != nil {
		return nil, err
	}
	c.setCreatorHeaders(req, session)
	req.Header.Set("Content-Type", "application/json")
	return c.do(req, endpoint)
}

func (c *Client) uploadFile(ctx context.Context, endpoint, field, path string, fields map[string]string, timeout time.Duration) (json.RawMessage, error) {
	session, err := c.Sessions.Session(ctx)
	if err != nil {
		return nil, err
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open upload file %q: %w", path, err)
	}
	defer file.Close()
	reader, pipeWriter := io.Pipe()
	writer := multipart.NewWriter(pipeWriter)
	contentType := writer.FormDataContentType()
	go func() {
		closeWithError := func(err error) {
			_ = pipeWriter.CloseWithError(err)
		}
		for key, value := range fields {
			if err := writer.WriteField(key, value); err != nil {
				closeWithError(err)
				return
			}
		}
		filename := filepath.Base(path)
		headers := make(textproto.MIMEHeader)
		headers.Set("Content-Disposition", multipart.FileContentDisposition(field, filename))
		contentType := mime.TypeByExtension(strings.ToLower(filepath.Ext(filename)))
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		headers.Set("Content-Type", contentType)
		part, err := writer.CreatePart(headers)
		if err != nil {
			closeWithError(err)
			return
		}
		if _, err := io.Copy(part, file); err != nil {
			closeWithError(err)
			return
		}
		if err := writer.Close(); err != nil {
			closeWithError(err)
			return
		}
		_ = pipeWriter.Close()
	}()
	defer reader.Close()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(c.APIBase, "/")+endpoint, reader)
	if err != nil {
		return nil, err
	}
	c.setCreatorHeaders(req, session)
	req.Header.Set("Content-Type", contentType)
	client := c.HTTP
	if timeout > 0 {
		clone := *c.HTTP
		clone.Timeout = timeout
		client = &clone
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	return decodeResponse(resp, endpoint)
}

func (c *Client) do(req *http.Request, endpoint string) (json.RawMessage, error) {
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	return decodeResponse(resp, endpoint)
}

func decodeResponse(resp *http.Response, endpoint string) (json.RawMessage, error) {
	defer resp.Body.Close()
	var envelope apiEnvelope
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return nil, fmt.Errorf("decode NewBeeBox %s response: %w", endpoint, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 || envelope.Code != 1 {
		return nil, &APIError{Endpoint: endpoint, HTTPStatus: resp.StatusCode, Code: envelope.Code, Message: redactMessage(envelope.Message)}
	}
	return envelope.Data, nil
}

func (c *Client) setCreatorHeaders(req *http.Request, session Session) {
	req.Header.Set("appId", "6")
	req.Header.Set("Authorization", "Bearer "+session.ResourceToken)
	req.Header.Set("token", session.AuthorToken)
	req.Header.Set("Accept-Language", "zh-CN")
}

func uploadMediaURL(data json.RawMessage) (string, error) {
	var payload any
	if err := json.Unmarshal(data, &payload); err != nil {
		return "", err
	}
	if value := stringFrom(payload); value != "" {
		return value, nil
	}
	if object := firstMap(payload); object != nil {
		if value := firstString(object, "media_url", "url", "name"); value != "" {
			return value, nil
		}
	}
	if list, ok := payload.([]any); ok && len(list) > 0 {
		if value := stringFrom(list[0]); value != "" {
			return value, nil
		}
	}
	return "", fmt.Errorf("media upload response did not contain media_url")
}

func intString(value int) string { return strconv.Itoa(value) }

var (
	bearerPattern    = regexp.MustCompile(`(?i)Bearer\s+[A-Za-z0-9._~+/=-]+`)
	jwtPattern       = regexp.MustCompile(`\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b`)
	signaturePattern = regexp.MustCompile(`(?i)(X-Amz-(?:Credential|Signature)=)[^&\s]+`)
)

func redactMessage(message string) string {
	message = bearerPattern.ReplaceAllString(message, "Bearer [REDACTED]")
	message = jwtPattern.ReplaceAllString(message, "[REDACTED_JWT]")
	return signaturePattern.ReplaceAllString(message, "${1}[REDACTED]")
}
