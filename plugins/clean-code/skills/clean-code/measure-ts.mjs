#!/usr/bin/env node
// measure-ts.mjs — function shape for TypeScript and JavaScript sources.
//
// Called by typescript.py for measure.py; run by hand only when debugging:
//   node measure-ts.mjs <path-to-node_modules/typescript> [--inline] <file>...
// Prints one JSON object {functions, unparsed}: `functions` holds
// {file, name, line, lines, cc, params, depth} rows.
//
// A .ts or .tsx file is parsed as TypeScript, every other file as JavaScript.
// With --inline, stdin is a JSON array of {file, text}: the inline scripts of
// HTML files, each padded so its lines are the lines of the HTML file.
//
// A file that does not parse, TypeScript or JavaScript, is a broken run: a
// script that checks only the exit code must see a real syntax error. The
// sloppy-mode octal forms are not errors (see SLOPPY_MODE_CODES). An inline
// script of an HTML file that does not parse goes to `unparsed` as
// {file, line, message} and the run goes on: a page template is not
// JavaScript until it is rendered.
//
// The typescript package is the measured project's own when it has one, so
// the parser matches the syntax the project compiles. Nothing is type-checked;
// imports need not resolve.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const [tsPackageDir, ...rest] = process.argv.slice(2);
const readsInline = rest.includes("--inline");
const files = rest.filter((arg) => arg !== "--inline");
if (!tsPackageDir || (files.length === 0 && !readsInline)) {
  console.error("usage: measure-ts.mjs <typescript-package-dir> [--inline] <file>...");
  process.exit(2);
}
const ts = createRequire(import.meta.url)(tsPackageDir);
const K = ts.SyntaxKind;

const FUNCTION_KINDS = new Set([
  K.FunctionDeclaration,
  K.MethodDeclaration,
  K.Constructor,
  K.GetAccessor,
  K.SetAccessor,
  K.ArrowFunction,
  K.FunctionExpression,
]);
const LOOP_KINDS = new Set([K.ForStatement, K.ForInStatement, K.ForOfStatement, K.WhileStatement, K.DoStatement]);
const BLOCK_KINDS = new Set([K.IfStatement, K.TryStatement, K.SwitchStatement, ...LOOP_KINDS]);
const BOOL_OPERATORS = new Set([K.AmpersandAmpersandToken, K.BarBarToken, K.QuestionQuestionToken]);

const EXPRESSION_KINDS = new Set([K.ArrowFunction, K.FunctionExpression]);

// A node that lends its name to the arrow or function expression assigned to it.
function isAssignmentTarget(node) {
  return (
    ts.isVariableDeclaration(node) ||
    ts.isPropertyAssignment(node) ||
    ts.isPropertyDeclaration(node) ||
    ts.isExportAssignment(node)
  );
}

// Rule (a): the expression is the initializer of a variable, an object
// property, a class property, or `export default`.
function isAssignedExpression(node) {
  return EXPRESSION_KINDS.has(node.kind) && Boolean(node.parent) && isAssignmentTarget(node.parent);
}

// The callee of a call as written: `it`, `vi.mock`, and `it.each` for the
// curried `it.each(rows)("title", fn)` and the tagged it.each`table`.
function calleeText(call) {
  const callee = call.expression;
  if (ts.isCallExpression(callee)) return callee.expression.getText();
  if (ts.isTaggedTemplateExpression(callee)) return callee.tag.getText();
  return callee.getText();
}

// A describe block groups tests the way a file groups functions: its length is
// the sum of its tests, not a job of its own. Its callback is not measured and
// does not own the callbacks inside it, so each test is measured by itself.
// `describe` anywhere in the callee covers describe.each and Playwright's
// test.describe; `suite` and `context` count only as the whole name's root.
const CONTAINER_ROOTS = new Set(["describe", "suite", "context"]);

function isContainerCall(call) {
  const parts = calleeText(call).split(".");
  return CONTAINER_ROOTS.has(parts[0]) || parts.includes("describe");
}

function isContainerCallback(node) {
  const call = node.parent;
  if (!EXPRESSION_KINDS.has(node.kind) || !call || !ts.isCallExpression(call)) return false;
  return call.arguments.includes(node) && isContainerCall(call);
}

// Rule (b): no function encloses this one, so it is measured nowhere else.
//
// Any enclosing function is enough; the check never asks whether that ancestor
// is itself measured, so it cannot recurse. Asking would also be pointless: the
// outermost function in a chain has no function above it, so it is always
// measured, and every callback below it therefore already has a measured owner.
function hasEnclosingFunction(node) {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (FUNCTION_KINDS.has(parent.kind) && !isContainerCallback(parent)) return true;
  }
  return false;
}

// An arrow or function expression is measured on its own when it is assigned a
// name (rule a) or when nothing encloses it (rule b — the orphan inside
// memo(...), forwardRef(...) or it(...) — describe blocks do not count as
// enclosing). Every other arrow, such as a callback passed to .map or useMemo,
// belongs to its enclosing function.
function isMeasured(node) {
  if (!FUNCTION_KINDS.has(node.kind) || isContainerCallback(node)) return false;
  if (EXPRESSION_KINDS.has(node.kind)) return isAssignedExpression(node) || !hasEnclosingFunction(node);
  return true;
}

function ownerName(node) {
  const owner = node.parent;
  return owner && owner.name ? owner.name.getText() : null;
}

// The nearest enclosing assignment target lends its name to a nameless
// expression: `Card` for memo(() => {}), `Loader.load` for a class property.
function assignedName(node) {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (ts.isVariableDeclaration(parent) || ts.isPropertyAssignment(parent)) return parent.name.getText();
    if (ts.isPropertyDeclaration(parent)) {
      const owner = ownerName(parent);
      return owner ? `${owner}.${parent.name.getText()}` : parent.name.getText();
    }
    if (ts.isExportAssignment(parent)) return "default";
  }
  return null;
}

const TITLE_LIMIT = 60;

// A callback nothing names is named after the call it is passed to, with the
// title when the first argument is a string: `it("adds numbers")`,
// `vi.mock("./api")`, `beforeEach()`.
function callName(node) {
  const call = node.parent;
  if (!call || !ts.isCallExpression(call) || !call.arguments.includes(node)) return null;
  const first = call.arguments[0];
  if (!first || !ts.isStringLiteralLike(first)) return `${calleeText(call)}()`;
  const title = first.text.length > TITLE_LIMIT ? `${first.text.slice(0, TITLE_LIMIT)}…` : first.text;
  return `${calleeText(call)}(${JSON.stringify(title)})`;
}

function nameOf(node) {
  if (ts.isConstructorDeclaration(node)) return `${ownerName(node) ?? "anonymous"}.constructor`;
  if (ts.isMethodDeclaration(node) || ts.isGetAccessor(node) || ts.isSetAccessor(node)) {
    const owner = ownerName(node);
    return owner ? `${owner}.${node.name.getText()}` : node.name.getText();
  }
  if (node.name) return node.name.getText();
  if (ts.isFunctionDeclaration(node)) return "default";
  return assignedName(node) ?? callName(node) ?? "anonymous";
}

function complexity(fn) {
  let cc = 1;
  const visit = (node) => {
    if (node !== fn && isMeasured(node)) return;
    if (
      node.kind === K.IfStatement ||
      node.kind === K.ConditionalExpression ||
      node.kind === K.CatchClause ||
      node.kind === K.CaseClause ||
      LOOP_KINDS.has(node.kind)
    ) {
      cc += 1;
    } else if (node.kind === K.BinaryExpression && BOOL_OPERATORS.has(node.operatorToken.kind)) {
      cc += 1;
    }
    ts.forEachChild(node, visit);
  };
  visit(fn);
  return cc;
}

function depth(fn) {
  const rec = (node, current) => {
    let best = current;
    ts.forEachChild(node, (child) => {
      if (isMeasured(child)) return;
      let next = current;
      if (BLOCK_KINDS.has(child.kind)) {
        const isElseIf = ts.isIfStatement(node) && ts.isIfStatement(child) && node.elseStatement === child;
        next = isElseIf ? current : current + 1;
      }
      best = Math.max(best, rec(child, next));
    });
    return best;
  };
  return rec(fn, 0);
}

// What the parser reports for JavaScript that runs in sloppy mode: a legacy
// octal literal (0755), an octal escape ("\033[0m"), a decimal with a leading
// zero, "\8". The scanner complains and the tree is whole, so the functions
// of such a file are measured.
const SLOPPY_MODE_CODES = new Set([1121, 1487, 1488, 1489]);

function isJavaScript(file) {
  return scriptKind(file) === ts.ScriptKind.JS;
}

// The parser accepts TypeScript syntax in a JavaScript file (`x: number`,
// `private`) and leaves the rejection to a later check; a one-file program
// runs that check. Nothing is resolved and no library is loaded.
function javaScriptDiagnostics(sf) {
  const host = {
    getSourceFile: (name) => (name === sf.fileName ? sf : undefined),
    getDefaultLibFileName: () => "lib.d.ts",
    writeFile: () => {},
    getCurrentDirectory: () => "/",
    getCanonicalFileName: (name) => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
    fileExists: (name) => name === sf.fileName,
    readFile: () => undefined,
  };
  const options = { allowJs: true, noResolve: true, noLib: true, noEmit: true };
  const program = ts.createProgram({ rootNames: [sf.fileName], options, host });
  return program.getSyntacticDiagnostics(sf).filter((diag) => !SLOPPY_MODE_CODES.has(diag.code));
}

// The first parse error of a source, or null. A source the parser could not
// read has no functions to report: measuring what the recovery parser
// invented would be a lie.
function parseError(sf, file) {
  const diagnostics = isJavaScript(file) ? javaScriptDiagnostics(sf) : (sf.parseDiagnostics ?? []);
  if (diagnostics.length === 0) return null;
  const diag = diagnostics[0];
  const line = sf.getLineAndCharacterOfPosition(diag.start ?? 0).line + 1;
  return { line, message: ts.flattenDiagnosticMessageText(diag.messageText, " ") };
}

// JavaScript covers .js, .mjs, .cjs, .jsx and the inline scripts of HTML files.
function scriptKind(file) {
  const name = file.toLowerCase();
  if (name.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (name.endsWith(".ts")) return ts.ScriptKind.TS;
  return ts.ScriptKind.JS;
}

function parse(file, text) {
  return ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, scriptKind(file));
}

function rowOf(node, sf) {
  const start = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;
  const end = sf.getLineAndCharacterOfPosition(node.getEnd()).line;
  return {
    name: nameOf(node),
    line: start + 1,
    lines: end - start + 1,
    cc: complexity(node),
    params: node.parameters.length,
    depth: depth(node),
  };
}

function measureSource(sf, file) {
  const out = [];
  const visit = (node) => {
    if (isMeasured(node)) out.push({ file, ...rowOf(node, sf) });
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

function fail(message) {
  console.error(message);
  process.exit(2);
}

// A file that is not UTF-8 is read one character per byte, as languages.py
// reads it: no line and no brace moves, and a letter of a single-byte encoding
// stays a letter. Replacement characters would make the parser call it binary.
function decode(bytes) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return bytes.toString("latin1");
  }
}

function readSource(file) {
  try {
    return decode(readFileSync(file));
  } catch (error) {
    return fail(`${file}: ${error.message}`);
  }
}

const functions = [];
const unparsed = [];

function measure(file, text, inline) {
  const sf = parse(file, text);
  const error = parseError(sf, file);
  if (!error) functions.push(...measureSource(sf, file));
  else if (inline) unparsed.push({ file, ...error });
  else fail(`${file}:${error.line}: ${error.message}`);
}

for (const file of files) measure(file, readSource(file), false);
for (const { file, text } of readsInline ? JSON.parse(readFileSync(0, "utf8")) : []) measure(file, text, true);
process.stdout.write(JSON.stringify({ functions, unparsed }));
