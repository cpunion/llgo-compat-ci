package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"go.yaml.in/yaml/v3"
)

const stressCase = "fixedbugs/issue79186.go"
const stressReason = "the full 51.2 million-operation RWMutex loop took 49-53s in five hosted WASI replays and exceeded the default 60s on another runner"

func preparePolicy(source []byte) ([]byte, error) {
	var config map[string]any
	if err := yaml.Unmarshal(source, &config); err != nil {
		return nil, err
	}
	if config == nil {
		return nil, fmt.Errorf("empty GOROOT policy")
	}
	entries, ok := config["timeouts"].([]any)
	if !ok {
		return nil, fmt.Errorf("GOROOT policy has no timeout sequence")
	}
	fallback := false
	for _, raw := range entries {
		entry, ok := raw.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("invalid timeout entry")
		}
		if entry["platform"] != "wasip1/wasm" || entry["directive"] != "run" || entry["case"] != stressCase {
			continue
		}
		fallback = fallback || entry["version"] == nil || entry["version"] == ""
		budget, err := time.ParseDuration(fmt.Sprint(entry["timeout"]))
		if err != nil {
			return nil, fmt.Errorf("invalid WASI RWMutex budget: %w", err)
		}
		// Preserve larger upstream budgets, including version-specific ones.
		if budget < 90*time.Second {
			entry["timeout"] = "90s"
			entry["reason"] = stressReason
		}
	}
	if !fallback {
		entries = append(entries, map[string]any{
			"platform": "wasip1/wasm", "directive": "run", "case": stressCase,
			"timeout": "90s", "reason": stressReason,
		})
	}
	config["timeouts"] = entries
	return yaml.Marshal(config)
}

func run() error {
	if len(os.Args) != 3 {
		return fmt.Errorf("usage: prepare.go SOURCE OUTPUT")
	}
	source, _ := filepath.Abs(os.Args[1])
	output, _ := filepath.Abs(os.Args[2])
	if source == output {
		return fmt.Errorf("output must differ from the upstream policy")
	}
	data, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	data, err = preparePolicy(data)
	if err != nil {
		return err
	}
	return os.WriteFile(output, data, 0o644)
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
