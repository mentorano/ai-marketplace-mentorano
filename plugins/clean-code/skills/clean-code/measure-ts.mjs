#!/usr/bin/env node
// measure-ts.mjs — function shape for TypeScript sources.
//
// Called by measure.py; run by hand only when debugging:
//   node measure-ts.mjs <path-to-node_modules/typescript> <file>...
// Prints one JSON array of {file, name, line, lines, cc, params, depth}.
//
// The typescript package is the measured project's own, so the parser matches
// the syntax the project compiles. Nothing is type-checked; imports need not
// resolve.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const [tsPackageDir, ...files] = process.argv.slice(2);
if (!tsPackageDir || files.length === 0) {
  console.error("usage: measure-ts.mjs <typescript-package-dir> <file>...");
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

// A file the parser could not read is a broken run, not a file with no
// functions: measuring what the recovery parser invented would be a lie.
function failOnParseErrors(sf, file) {
  const diagnostics = sf.parseDiagnostics ?? [];
  if (diagnostics.length === 0) return;
  const diag = diagnostics[0];
  const line = sf.getLineAndCharacterOfPosition(diag.start ?? 0).line + 1;
  console.error(`${file}:${line}: ${ts.flattenDiagnosticMessageText(diag.messageText, " ")}`);
  process.exit(2);
}

function measureFile(file) {
  const text = readFileSync(file, "utf8");
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  failOnParseErrors(sf, file);
  const out = [];
  const visit = (node) => {
    if (isMeasured(node)) {
      const start = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;
      const end = sf.getLineAndCharacterOfPosition(node.getEnd()).line;
      out.push({
        file,
        name: nameOf(node),
        line: start + 1,
        lines: end - start + 1,
        cc: complexity(node),
        params: node.parameters.length,
        depth: depth(node),
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

const results = [];
for (const file of files) {
  try {
    results.push(...measureFile(file));
  } catch (error) {
    console.error(`${file}: ${error.message}`);
    process.exit(2);
  }
}
process.stdout.write(JSON.stringify(results));
