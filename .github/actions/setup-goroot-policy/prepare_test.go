package main

import (
	"bytes"
	"reflect"
	"testing"

	"go.yaml.in/yaml/v3"
)

func TestPolicyPreservesClassificationsAndOtherBudgets(t *testing.T) {
	source := []byte(`host_skips:
  - case: original-host-skip.go
xfails:
  - case: original-xfail.go
flakes:
  - case: original-flake.go
timeouts:
  - platform: js/wasm
    directive: run
    case: fixedbugs/issue79186.go
    timeout: 4m
  - platform: wasip1/wasm
    directive: run
    case: unrelated.go
    timeout: 12s
`)
	result, err := preparePolicy(source)
	if err != nil {
		t.Fatal(err)
	}
	var before, after map[string]any
	yaml.Unmarshal(source, &before)
	yaml.Unmarshal(result, &after)
	oldEntries := before["timeouts"].([]any)
	newEntries := after["timeouts"].([]any)
	if len(newEntries) != len(oldEntries)+1 || !reflect.DeepEqual(oldEntries, newEntries[:len(oldEntries)]) {
		t.Fatalf("unrelated timeout entries changed: %s", result)
	}
	entry := newEntries[len(oldEntries)].(map[string]any)
	if entry["platform"] != "wasip1/wasm" || entry["case"] != stressCase || entry["directive"] != "run" || entry["timeout"] != "90s" {
		t.Fatalf("unexpected hosted budget: %#v", entry)
	}
	delete(before, "timeouts")
	delete(after, "timeouts")
	if !reflect.DeepEqual(before, after) {
		t.Fatal("classifications changed")
	}
	again, err := preparePolicy(result)
	if err != nil || !bytes.Equal(result, again) {
		t.Fatalf("policy is not idempotent: %v", err)
	}
}

func TestPolicyRetainsLargerUpstreamBudgets(t *testing.T) {
	for _, budget := range []string{"30s", "90s", "4m"} {
		source, err := yaml.Marshal(map[string]any{"timeouts": []any{map[string]any{
			"platform": "wasip1/wasm", "directive": "run", "case": stressCase, "timeout": budget,
		}}})
		if err != nil {
			t.Fatal(err)
		}
		result, err := preparePolicy(source)
		if err != nil {
			t.Fatal(err)
		}
		var config map[string]any
		yaml.Unmarshal(result, &config)
		entries := config["timeouts"].([]any)
		want := budget
		if budget == "30s" {
			want = "90s"
		}
		if len(entries) != 1 || entries[0].(map[string]any)["timeout"] != want {
			t.Fatalf("upstream %s budget changed incorrectly: %s", budget, result)
		}
	}
}

func TestPolicyRejectsInvalidInput(t *testing.T) {
	for _, source := range []string{"", "timeouts: wrong", "timeouts: [wrong]", "timeouts: ["} {
		if _, err := preparePolicy([]byte(source)); err == nil {
			t.Fatalf("accepted invalid policy %q", source)
		}
	}
}
