//go:build !windows

package newbee

import "os"

func replaceFile(source, destination string) error {
	return os.Rename(source, destination)
}
