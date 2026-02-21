/**
 * Form Field Accessibility & Autofill Validator
 *
 * Checks compiled React HTML for:
 *   1. Missing id/name on input, select, textarea elements
 *   2. Duplicate id attributes
 *   3. Missing label associations (for= or wrapping <label>)
 *
 * Usage:
 *   node scripts/check_form_fields.js <html-file>
 *   node scripts/check_form_fields.js dist/index.html
 *   node scripts/check_form_fields.js --scan-tsx   # scan .tsx source files directly
 *
 * Requires: jsdom (npm install jsdom)
 */

const fs = require("fs");
const path = require("path");

// ── HTML mode: parse rendered HTML with jsdom ──────────────────────

function checkHtmlFile(filePath) {
  let JSDOM;
  try {
    JSDOM = require("jsdom").JSDOM;
  } catch {
    console.error("ERROR: jsdom not installed. Run: npm install jsdom");
    process.exit(1);
  }

  const html = fs.readFileSync(filePath, "utf8");
  const dom = new JSDOM(html);
  const doc = dom.window.document;

  const inputs = Array.from(
    doc.querySelectorAll("input, select, textarea")
  );

  const issues = {
    missingIdOrName: [],
    duplicateIds: {},
    missingLabel: [],
  };

  const idMap = new Map();

  for (const el of inputs) {
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute("type") || "";
    const id = el.getAttribute("id");
    const name = el.getAttribute("name");

    // Skip non-data inputs
    if (tag === "input" && ["button", "submit", "reset", "hidden"].includes(type)) {
      continue;
    }

    if (!id && !name) {
      issues.missingIdOrName.push({ tag, type, outerHTML: el.outerHTML.slice(0, 120) });
    }

    if (id) {
      if (!idMap.has(id)) idMap.set(id, []);
      idMap.get(id).push(el.outerHTML.slice(0, 120));
    }

    // Label association check
    const hasLabelFor =
      id && doc.querySelector(`label[for="${id}"]`) !== null;
    const isWrapped =
      el.parentElement && el.parentElement.tagName.toLowerCase() === "label";

    if (!hasLabelFor && !isWrapped) {
      issues.missingLabel.push({
        tag, type, id: id || null, name: name || null,
        outerHTML: el.outerHTML.slice(0, 120),
      });
    }
  }

  for (const [id, els] of idMap.entries()) {
    if (els.length > 1) {
      issues.duplicateIds[id] = els;
    }
  }

  return issues;
}

// ── TSX scan mode: regex-based scan of source files ────────────────

function scanTsxFiles(srcDir) {
  const issues = {
    missingIdOrName: [],
    duplicateIds: {},
    missingLabel: [],
  };

  const idMap = new Map();
  const files = findTsxFiles(srcDir);

  // Patterns for form elements in JSX
  const formElRegex = /<(input|select|textarea)\b([^>]*?)(?:\/>|>)/gi;
  const idRegex = /\bid\s*=\s*(?:{[^}]*}|"[^"]*"|'[^']*')/;
  const nameRegex = /\bname\s*=\s*(?:{[^}]*}|"[^"]*"|'[^']*')/;
  const typeRegex = /\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|{[^}]*})/;
  const htmlForRegex = /\bhtmlFor\s*=\s*(?:{[^}]*}|"([^"]*)"|'([^']*)')/;

  for (const file of files) {
    const content = fs.readFileSync(file, "utf8");
    const relPath = path.relative(srcDir, file);
    const lines = content.split("\n");

    // Collect htmlFor values in this file
    const htmlForValues = new Set();
    for (const line of lines) {
      const m = line.match(htmlForRegex);
      if (m) htmlForValues.add(m[1] || m[2] || "dynamic");
    }

    let match;
    formElRegex.lastIndex = 0;
    while ((match = formElRegex.exec(content)) !== null) {
      const tag = match[1].toLowerCase();
      const attrs = match[2] || "";
      const snippet = match[0].slice(0, 120);

      // Find line number
      const beforeMatch = content.slice(0, match.index);
      const lineNum = (beforeMatch.match(/\n/g) || []).length + 1;

      const typeMatch = attrs.match(typeRegex);
      const type = typeMatch ? (typeMatch[1] || typeMatch[2] || "dynamic") : "";

      // Skip non-data inputs
      if (tag === "input" && ["button", "submit", "reset", "hidden"].includes(type)) {
        continue;
      }

      const hasId = idRegex.test(attrs);
      const hasName = nameRegex.test(attrs);

      if (!hasId && !hasName) {
        issues.missingIdOrName.push({
          file: relPath, line: lineNum, tag, type, snippet,
        });
      }

      // Extract id value for duplicate check
      if (hasId) {
        const idValMatch = attrs.match(/\bid\s*=\s*"([^"]*)"/);
        if (idValMatch) {
          const idVal = idValMatch[1];
          if (!idMap.has(idVal)) idMap.set(idVal, []);
          idMap.get(idVal).push({ file: relPath, line: lineNum });
        }
      }

      // Label check: does this element have an id that matches an htmlFor?
      if (!hasId) {
        issues.missingLabel.push({
          file: relPath, line: lineNum, tag, type, snippet,
          reason: "no id attribute — cannot be associated with a label",
        });
      }
    }
  }

  for (const [id, locations] of idMap.entries()) {
    if (locations.length > 1) {
      issues.duplicateIds[id] = locations;
    }
  }

  return issues;
}

function findTsxFiles(dir) {
  const results = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory() && entry.name !== "node_modules" && entry.name !== "__tests__") {
      results.push(...findTsxFiles(fullPath));
    } else if (entry.isFile() && (entry.name.endsWith(".tsx") || entry.name.endsWith(".jsx"))) {
      results.push(fullPath);
    }
  }
  return results;
}

// ── CLI ─────────────────────────────────────────────────────────────

function printReport(issues, mode) {
  const total =
    issues.missingIdOrName.length +
    Object.keys(issues.duplicateIds).length +
    issues.missingLabel.length;

  console.log(`\n=== Form Field Validation (${mode}) ===\n`);

  if (issues.missingIdOrName.length > 0) {
    console.log(`Missing id/name (${issues.missingIdOrName.length}):`);
    for (const item of issues.missingIdOrName) {
      if (item.file) {
        console.log(`  ${item.file}:${item.line} <${item.tag} type="${item.type}">`);
      } else {
        console.log(`  <${item.tag} type="${item.type}"> ${item.outerHTML}`);
      }
    }
    console.log();
  }

  if (Object.keys(issues.duplicateIds).length > 0) {
    console.log(`Duplicate ids (${Object.keys(issues.duplicateIds).length}):`);
    for (const [id, els] of Object.entries(issues.duplicateIds)) {
      console.log(`  id="${id}" appears ${els.length} times`);
      for (const el of els) {
        if (typeof el === "string") {
          console.log(`    ${el}`);
        } else {
          console.log(`    ${el.file}:${el.line}`);
        }
      }
    }
    console.log();
  }

  if (issues.missingLabel.length > 0) {
    console.log(`Missing label association (${issues.missingLabel.length}):`);
    for (const item of issues.missingLabel) {
      if (item.file) {
        console.log(`  ${item.file}:${item.line} <${item.tag}> — ${item.reason}`);
      } else {
        console.log(`  <${item.tag} id="${item.id}" name="${item.name}">`);
      }
    }
    console.log();
  }

  if (total === 0) {
    console.log("All form fields have proper id/name and label associations.");
  } else {
    console.log(`Total issues: ${total}`);
  }

  return total;
}

// ── Main ────────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.includes("--scan-tsx")) {
  const srcDir = path.resolve(__dirname, "..", "web", "react", "src");
  if (!fs.existsSync(srcDir)) {
    console.error(`ERROR: Source directory not found: ${srcDir}`);
    process.exit(1);
  }
  const issues = scanTsxFiles(srcDir);
  if (args.includes("--json")) {
    console.log(JSON.stringify(issues, null, 2));
  } else {
    const total = printReport(issues, "TSX source scan");
    process.exit(total > 0 ? 1 : 0);
  }
} else if (args.length > 0 && !args[0].startsWith("--")) {
  const target = args[0];
  if (!fs.existsSync(target)) {
    console.error(`ERROR: File not found: ${target}`);
    process.exit(1);
  }
  const issues = checkHtmlFile(target);
  if (args.includes("--json")) {
    console.log(JSON.stringify(issues, null, 2));
  } else {
    const total = printReport(issues, "HTML");
    process.exit(total > 0 ? 1 : 0);
  }
} else {
  console.log("Usage:");
  console.log("  node scripts/check_form_fields.js <html-file>        # Check rendered HTML");
  console.log("  node scripts/check_form_fields.js --scan-tsx          # Scan TSX source files");
  console.log("  node scripts/check_form_fields.js --scan-tsx --json   # JSON output");
  process.exit(0);
}
