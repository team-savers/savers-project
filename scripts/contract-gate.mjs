#!/usr/bin/env node
// Contract gate: statically validates an OpenAPI file for defects that
// openapi-spec-validator (syntax-only) misses but reviewers keep flagging.
//
// Usage:
//   node scripts/contract-gate.mjs <openapi.yaml> [--json]
//
// Exit codes:
//   0  pass (zero violations)
//   1  violations found (warnings do not affect this)
//   2  execution error (file missing, parse failure, etc.)
//
// YAML is parsed via the repo's existing Python `yaml` toolchain through a
// child_process shim — no npm dependency is added. Only Node's standard
// library is otherwise used.
//
// --- What this checks (and what it deliberately does not) ---------------
// Checks implemented:
//   C1  the `nullable` keyword in the wrong dialect.
//       In OpenAPI 3.0.x, `required` + null-permitting (any idiom) is a
//       violation because 3.0 code generators silently drop `nullable`,
//       turning `answer=null` into a type error.
//       In OpenAPI 3.1.x, the literal `nullable` keyword is ignored (it was
//       removed from the spec); its presence is itself a defect regardless
//       of `required`. The 3.1 idioms for null — `type: [X, "null"]` and
//       `oneOf`/`anyOf` with a `{type: "null"}` member — are CORRECT and
//       must NOT be flagged.
//   C2  description ↔ example digit-count drift for Korean "N자리" claims.
//       A description that promises "8자리" next to an example of a
//       different length is a reviewer-visible lie.
//   C3  ambiguous phrasing ("~하거나", "권장", "기본적으로", …).
//       Warning-level: these phrases turn a contract into a suggestion.
//   C5  nullable property missing from `required` (OpenAPI 3.1).
//       Warning-level: when null is a *meaningful* value (a "definite
//       signal", e.g. answer=null meaning "no evidence"), omitting the
//       key makes null indistinguishable from "key absent" / "response
//       truncated". Such fields belong in `required`. Genuinely optional
//       nullable fields (e.g. bjdCode) are still valid and may ignore
//       this warning.
//
// Deliberately NOT checked:
//   "Does a write path exist for this field?" — i.e. flagging fields that
//   appear only in responses. Deciding whether a field needs a producer
//   requires domain semantics (read-only fields like `name`, `issuedAt`,
//   `title` are normal; only a few like `lastResponse` are true orphans),
//   and any purely mechanical rule collides with the read-only majority
//   and buries the real signal in noise. Measured on this spec, the rule
//   produced 36 false positives against ~2 intended hits. A noisy check
//   trains reviewers to ignore all warnings, which is worse than no check.
//   This class of concern belongs in human review or a separate semantic
//   audit, not in a syntactic gate.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import process from "node:process";

// --- CLI parsing ---------------------------------------------------------

const args = process.argv.slice(2);
const jsonOnlyFlag = args.includes("--json");
const positional = args.filter((a) => a !== "--json");

if (positional.length !== 1) {
  process.stderr.write(
    "Usage: node scripts/contract-gate.mjs <openapi.yaml> [--json]\n",
  );
  process.exit(2);
}

const specPath = positional[0];

// --- YAML load via Python (no npm deps) ----------------------------------

function loadYaml(path) {
  // Python reads the file and emits canonical JSON as UTF-8 bytes. We force
  // stdout to utf-8 because Windows defaults to a locale codec (cp949) that
  // cannot encode the Korean text and dashes this spec contains. Piping
  // raw bytes (rather than relying on text mode) sidesteps that entirely.
  const script = `
import json, sys, yaml, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
except FileNotFoundError:
    sys.stdout.write(json.dumps({"__error__": "FileNotFoundError"}))
    sys.exit(0)
except yaml.YAMLError as e:
    sys.stdout.write(json.dumps({"__error__": "YAMLError", "detail": str(e)}))
    sys.exit(0)
sys.stdout.write(json.dumps(doc, ensure_ascii=False))
`;
  const result = spawnSync("python", ["-c", script, path], {
    encoding: "utf8",
  });
  if (result.status !== 0 || result.error) {
    throw new Error(
      `python yaml invocation failed: ${result.error?.message ?? result.stderr ?? result.stdout}`,
    );
  }
  const parsed = JSON.parse(result.stdout);
  if (parsed && typeof parsed === "object" && parsed.__error__) {
    if (parsed.__error__ === "FileNotFoundError") {
      const e = new Error(`File not found: ${path}`);
      e.code = "ENOENT";
      throw e;
    }
    throw new Error(`YAML parse error: ${parsed.detail ?? "(no detail)"}`);
  }
  return parsed;
}

let doc;
try {
  doc = loadYaml(specPath);
} catch (e) {
  if (e.code === "ENOENT") {
    process.stderr.write(`Error: file not found: ${specPath}\n`);
    process.exit(2);
  }
  process.stderr.write(`Error: ${e.message}\n`);
  process.exit(2);
}

if (!doc || typeof doc !== "object" || !doc.openapi) {
  process.stderr.write(
    `Error: ${specPath} does not look like an OpenAPI document (missing 'openapi' field)\n`,
  );
  process.exit(2);
}

const openapiVersion = String(doc.openapi);
const isV31 = openapiVersion.startsWith("3.1");
const isV30 = openapiVersion.startsWith("3.0");

// --- Schema traversal utilities ------------------------------------------

const violations = [];
const warnings = [];

function addViolation(check, path, message) {
  violations.push({ check, path, message });
}
function addWarning(check, path, message) {
  warnings.push({ check, path, message });
}

// A schema is considered nullable under various OpenAPI idioms.
//  - 3.0: top-level `nullable: true` on the schema (also applies through
//    allOf/oneOf/anyOf merge in the relevant generators; we treat the
//    property's own schema node holistically).
//  - 3.1: `type` may be an array including "null", or `oneOf`/`anyOf` may
//    contain a `{type: "null"}` member.
//
// Used by C1's 3.0 branch and by C5. NOT used by C1's 3.1 branch, which
// cares only about the literal `nullable` keyword (see hasNullableKeyword).
function isSchemaNullable(schema) {
  if (!schema || typeof schema !== "object") return false;
  if (schema.nullable === true) return true; // 3.0 idiom (also a defect in 3.1)
  // 3.1 array form
  if (Array.isArray(schema.type) && schema.type.includes("null")) return true;
  // Compositions: a nullable member makes the whole nullable.
  for (const key of ["oneOf", "anyOf"]) {
    const arr = schema[key];
    if (Array.isArray(arr)) {
      for (const member of arr) {
        if (member && member.type === "null") return true;
        if (Array.isArray(member?.type) && member.type.includes("null")) {
          return true;
        }
      }
    }
  }
  // allOf: conservatively, if any composed member is nullable we treat the
  // merged result as nullable. This matches how a `nullable` placed next to
  // an `allOf` works in OpenAPI 3.0 generators.
  if (Array.isArray(schema.allOf)) {
    for (const member of schema.allOf) {
      if (isSchemaNullable(member)) return true;
    }
  }
  return false;
}

// Detects the LITERAL `nullable: true` keyword — the OpenAPI 3.0 idiom that
// 3.1 removed and now ignores. Used by C1's 3.1 branch only. This is
// deliberately distinct from isSchemaNullable: the 3.1 null idioms
// (`type: [X, "null"]`, `oneOf`/`anyOf` with `{type:"null"}`) are CORRECT
// and must NOT trigger this function, whereas isSchemaNullable treats them
// as nullable for C5's "is this field null-permitting?" question.
//
// Recurses into allOf/oneOf/anyOf members because a `nullable: true` buried
// in a composition is still the same defect (the keyword is ignored by 3.1
// wherever it sits in the schema tree).
function hasNullableKeyword(schema) {
  if (!schema || typeof schema !== "object") return false;
  if (schema.nullable === true) return true;
  for (const key of ["allOf", "oneOf", "anyOf"]) {
    const arr = schema[key];
    if (Array.isArray(arr)) {
      for (const member of arr) {
        if (hasNullableKeyword(member)) return true;
      }
    }
  }
  return false;
}

// --- C1: the `nullable` keyword in the wrong dialect ---------------------
// In 3.0.x, `required` + null-permitting (any idiom — `nullable: true`,
// `type:[X,"null"]`, oneOf/anyOf with {type:"null"}) is a violation because
// 3.0 code generators silently drop the null hint and turn `answer=null`
// into a type error.
// In 3.1.x, the literal `nullable` keyword was removed and is ignored, so
// its mere presence (anywhere in the schema, including inside
// allOf/oneOf/anyOf) is itself a defect — independent of `required`. The
// 3.1 null idioms (`type:[X,"null"]`, oneOf/anyOf with {type:"null"}) are
// the CORRECT way to express nullability and must NOT be flagged here.

function checkC1() {
  const schemas = doc.components?.schemas ?? {};
  for (const [schemaName, schema] of Object.entries(schemas)) {
    if (!schema || typeof schema !== "object") continue;
    const props = schema.properties ?? {};
    if (!props || typeof props !== "object") continue;
    if (isV31) {
      // 3.1: scan EVERY property (required or not) for the literal
      // `nullable` keyword. A `nullable` on an optional field is the same
      // defect — the keyword is silently ignored, so the author's intent
      // (null-permitting) is lost without a peep from tooling.
      for (const [fieldName, prop] of Object.entries(props)) {
        if (!prop || typeof prop !== "object") continue;
        if (hasNullableKeyword(prop)) {
          addViolation(
            "C1",
            `components.schemas.${schemaName}.${fieldName}`,
            `OpenAPI 3.1 removed the 'nullable' keyword; tools now ignore it silently, so the author's null-permitting intent is lost. Use the 3.1 idiom instead: \`type: [X, "null"]\` or \`oneOf\`/\`anyOf\` with a \`{type: "null"}\` member. (The forms \`type: [X, "null"]\` and \`oneOf\`/\`anyOf\` with \`{type: "null"}\` are correct and are NOT flagged.)`,
          );
        }
      }
    } else if (isV30) {
      // 3.0: only `required` + null-permitting is a violation. Optional +
      // nullable is fine in 3.0.
      const requiredList = Array.isArray(schema.required) ? schema.required : [];
      if (requiredList.length === 0) continue;
      for (const fieldName of requiredList) {
        const prop = props[fieldName];
        if (!prop) continue; // unresolved required — separate concern, not C1
        if (isSchemaNullable(prop)) {
          addViolation(
            "C1",
            `components.schemas.${schemaName}.${fieldName}`,
            `Required + nullable is not portably preserved by 3.0 code generators (nullable is silently dropped, turning answer=null into a type error). Re-express via oneOf or move nullability to a non-required companion field.`,
          );
        }
      }
    }
  }
}

// --- C2: description <-> example digit-count -----------------------------

// Matches "N자리" or "N 자리" (with or without a space) inside Korean
// descriptions. Captures the digit run.
const DIGIT_PATTERN = /(\d+)\s*자리/g;

function checkC2() {
  // Iterate over every schema property that carries both a description with
  // a digit-count claim and a string example. Inline path parameters are
  // covered via the paths walk below.
  const visit = (schema, basePath) => {
    if (!schema || typeof schema !== "object") return;
    const props = schema.properties ?? {};
    for (const [name, prop] of Object.entries(props)) {
      if (!prop || typeof prop !== "object") continue;
      const path = `${basePath}.${name}`;
      checkC2One(prop, path);
      // Recurse into nested object schemas (skip refs — they are visited at
      // their own definition site).
      if (prop.type === "object" && prop.properties) {
        visit(prop, path);
      }
    }
  };

  // Component-level schemas
  const schemas = doc.components?.schemas ?? {};
  for (const [name, schema] of Object.entries(schemas)) {
    visit(schema, `components.schemas.${name}`);
  }

  // Operation parameters and request bodies (these often carry their own
  // description+example pairs outside the components tree).
  const paths = doc.paths ?? {};
  for (const [pathItem, item] of Object.entries(paths)) {
    if (!item || typeof item !== "object") continue;
    for (const method of Object.keys(item)) {
      if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
      const op = item[method];
      if (!op || typeof op !== "object") continue;
      const opPath = `paths.${pathItem}.${method}`;
      const params = Array.isArray(op.parameters) ? op.parameters : [];
      for (let i = 0; i < params.length; i++) {
        const p = params[i];
        const pPath = `${opPath}.parameters[${i}]`;
        // A parameter's `description` can sit on the parameter itself while
        // its `example` lives under `schema`. Handle both placements:
        // parameter-level description vs schema-level example, and the
        // straightforward schema-level description+example pair.
        const schema = p?.schema;
        if (schema && typeof schema === "object") {
          if (typeof p.description === "string" && schema.example !== undefined) {
            // Synthetic node so checkC2One compares param description to
            // schema example. Use a copy to avoid mutating the loaded doc.
            checkC2One(
              { description: p.description, example: schema.example },
              pPath,
            );
          }
          checkC2One(schema, pPath);
        }
      }
      const bodySchema = op.requestBody?.content?.["application/json"]?.schema;
      if (bodySchema && bodySchema.properties) {
        visit(bodySchema, `${opPath}.requestBody`);
      }
    }
  }
}

function checkC2One(prop, path) {
  const desc = typeof prop.description === "string" ? prop.description : "";
  if (!desc) return;
  // Reset lastIndex because DIGIT_PATTERN is stateful and reused.
  DIGIT_PATTERN.lastIndex = 0;
  const matches = [...desc.matchAll(DIGIT_PATTERN)];
  if (matches.length === 0) return;
  const example = prop.example;
  if (typeof example !== "string") return; // nothing to compare against
  for (const m of matches) {
    const claimed = Number(m[1]);
    const actual = [...example].length;
    if (claimed !== actual) {
      addViolation(
        "C2",
        path,
        `Description claims ${claimed}자리 but example '${example}' is ${actual} characters.`,
      );
    }
  }
}

// --- C3: ambiguous phrasing ----------------------------------------------

// Each pattern is a human-phrasing smell that turns a contract into a
// suggestion. These are warnings, not failures, because the same phrases
// appear legitimately in background prose.
const AMBIGUOUS_PATTERNS = [
  { re: /하거나/g, label: "'~하거나' (offers alternatives)" },
  { re: /또는\s*\S*\s*할\s*수\s*있/g, label: "'또는 ~할 수 있' (optional path)" },
  { re: /권장/g, label: "'권장' (recommendation, not requirement)" },
  { re: /일\s*수\s*있습니/g, label: "'~일 수 있습니다' (possibility)" },
  { re: /가능하면/g, label: "'가능하면' (best-effort)" },
  { re: /대체로/g, label: "'대체로' (usually)" },
  { re: /기본적으로/g, label: "'기본적으로' (by default — ambiguous)" },
];

function checkC3() {
  const visitSchema = (schema, basePath) => {
    if (!schema || typeof schema !== "object") return;
    if (typeof schema.description === "string") {
      scanText(schema.description, basePath);
    }
    const props = schema.properties ?? {};
    for (const [name, prop] of Object.entries(props)) {
      if (!prop || typeof prop !== "object") continue;
      const path = `${basePath}.${name}`;
      if (typeof prop.description === "string") {
        scanText(prop.description, path);
      }
      if (prop.type === "object" && prop.properties) {
        visitSchema(prop, path);
      }
    }
  };

  const schemas = doc.components?.schemas ?? {};
  for (const [name, schema] of Object.entries(schemas)) {
    visitSchema(schema, `components.schemas.${name}`);
  }

  const paths = doc.paths ?? {};
  for (const [pathItem, item] of Object.entries(paths)) {
    if (!item || typeof item !== "object") continue;
    if (typeof item.description === "string") {
      scanText(item.description, `paths.${pathItem}`);
    }
    for (const method of Object.keys(item)) {
      if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
      const op = item[method];
      if (!op || typeof op !== "object") continue;
      const opPath = `paths.${pathItem}.${method}`;
      if (typeof op.description === "string") {
        scanText(op.description, opPath);
      }
      const params = Array.isArray(op.parameters) ? op.parameters : [];
      for (let i = 0; i < params.length; i++) {
        const p = params[i];
        if (typeof p?.description === "string") {
          scanText(p.description, `${opPath}.parameters[${i}]`);
        }
        if (p?.schema && typeof p.schema.description === "string") {
          scanText(p.schema.description, `${opPath}.parameters[${i}].schema`);
        }
      }
    }
  }

  // Top-level info.description
  const infoDesc = doc.info?.description;
  if (typeof infoDesc === "string") {
    scanText(infoDesc, "info.description");
  }
}

function scanText(text, path) {
  for (const { re, label } of AMBIGUOUS_PATTERNS) {
    re.lastIndex = 0;
    if (re.test(text)) {
      addWarning("C3", path, `Ambiguous phrasing: ${label}`);
    }
  }
}

// --- C5: nullable property missing from required (3.1) -------------------
// In OpenAPI 3.1 the clean way to say "the key always exists, the value may
// be null" is to (a) list the field in `required` AND (b) include "null" in
// its `type` (or via oneOf/anyOf). When a property is nullable but NOT in
// `required`, clients cannot distinguish `null` (a meaningful value) from
// "key absent" (truncation, version skew) — which is especially damaging
// for fields whose null is itself the measured signal (e.g. ChatResponse.answer).
//
// This is a WARNING, not a violation: genuinely-optional nullable fields
// (bjdCode, bearing, capacity, …) are legitimate and the rule would be too
// noisy as a hard failure. The point is to make a reviewer look twice.
//
// Note: C1 fires on the opposite mistake (required + `nullable` keyword).
// C5 is about required + *3.1-style* nullability being *missing*.

function checkC5() {
  // Only meaningful under 3.1, where `type: [string, "null"]` is the
  // idiomatic way to express nullability. Under 3.0, `nullable: true` on a
  // non-required field is fine and C1 already covers the required case.
  if (!isV31) return;
  const schemas = doc.components?.schemas ?? {};
  for (const [schemaName, schema] of Object.entries(schemas)) {
    if (!schema || typeof schema !== "object") continue;
    const props = schema.properties ?? {};
    if (!props || typeof props !== "object") continue;
    const requiredSet = new Set(
      Array.isArray(schema.required) ? schema.required : [],
    );
    for (const [fieldName, prop] of Object.entries(props)) {
      if (!prop || typeof prop !== "object") continue;
      if (requiredSet.has(fieldName)) continue; // already required — fine
      if (!isSchemaNullable(prop)) continue; // not nullable — out of scope
      addWarning(
        "C5",
        `components.schemas.${schemaName}.${fieldName}`,
        `This property is nullable but not listed in the schema's 'required'. ` +
          `When null is a meaningful value (a definite signal, not "unknown"), ` +
          `omitting the key makes "value=null" indistinguishable from "key absent" ` +
          `(truncation, version skew), which can invalidate metrics that count nulls. ` +
          `If null is a definite signal, add this field to 'required'. ` +
          `If the field is genuinely optional (null means "not applicable / unknown"), ` +
          `this warning may be ignored.`,
      );
    }
  }
}

// --- Run all checks ------------------------------------------------------

checkC1();
checkC2();
checkC3();
checkC5();

const verdict = {
  spec: specPath,
  openapiVersion,
  pass: violations.length === 0,
  violations,
  warnings,
  counts: { violations: violations.length, warnings: warnings.length },
};

function renderHumanSummary() {
  const lines = [];
  lines.push(`spec:             ${verdict.spec}`);
  lines.push(`openapiVersion:   ${verdict.openapiVersion}`);
  lines.push(
    `result:           ${verdict.pass ? "PASS" : "FAIL"}  (${violations.length} violations, ${warnings.length} warnings)`,
  );
  lines.push("");
  if (violations.length > 0) {
    lines.push(`== violations (${violations.length}) ==`);
    for (const v of violations) {
      lines.push(`[${v.check}] ${v.path}`);
      lines.push(`    ${v.message}`);
    }
    lines.push("");
  }
  if (warnings.length > 0) {
    lines.push(`== warnings (${warnings.length}) ==`);
    for (const w of warnings) {
      lines.push(`[${w.check}] ${w.path}`);
      lines.push(`    ${w.message}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

if (jsonOnlyFlag) {
  process.stdout.write(JSON.stringify(verdict) + "\n");
} else {
  process.stdout.write(renderHumanSummary() + "\n");
  process.stdout.write(JSON.stringify(verdict) + "\n");
}

process.exit(violations.length === 0 ? 0 : 1);
