import { readFileSync } from 'node:fs';
import { parse } from 'acorn';

const code = readFileSync('src/app.js', 'utf8');
const ast = parse(code, { ecmaVersion: 2022, sourceType: 'module' });

// 模块级声明
const moduleNames = new Set();
for (const n of ast.body) {
  if (n.type === 'VariableDeclaration') { for (const d of n.declarations) collectPattern(d.id, moduleNames); }
  else if (n.type === 'FunctionDeclaration' && n.id) moduleNames.add(n.id.name);
  else if (n.type === 'ImportDeclaration') { for (const s of n.specifiers) moduleNames.add(s.local.name); }
  else if (n.type === 'ExportNamedDeclaration' && n.declaration) {
    const d = n.declaration;
    if (d.type === 'VariableDeclaration') { for (const dd of d.declarations) collectPattern(dd.id, moduleNames); }
    else if (d.type === 'FunctionDeclaration' && d.id) moduleNames.add(d.id.name);
  }
}
function collectPattern(p, out) {
  if (!p) return;
  switch (p.type) {
    case 'Identifier': out.add(p.name); break;
    case 'ObjectPattern': for (const pr of p.properties) collectPattern(pr.type === 'RestElement' ? pr.argument : pr.value, out); break;
    case 'ArrayPattern': for (const el of p.elements) collectPattern(el, out); break;
    case 'AssignmentPattern': collectPattern(p.left, out); break;
    case 'RestElement': collectPattern(p.argument, out); break;
  }
}

const KNOWN = new Set(['window','document','globalThis','app','Vue','localStorage','navigator','location','history','confirm','alert','prompt','EventSource','Image','FileReader','Blob','URL','URLSearchParams','FormData','WebSocket','MutationObserver','ResizeObserver','requestAnimationFrame','cancelAnimationFrame','requestIdleCallback','setTimeout','clearTimeout','setInterval','clearInterval','console','Math','JSON','Object','Array','String','Number','Boolean','Date','RegExp','Map','Set','WeakMap','WeakSet','Promise','Symbol','parseInt','parseFloat','isNaN','isFinite','encodeURIComponent','decodeURIComponent','axios','$','jQuery','pinyinPro','sortFileByName','getFileIconClass','getFileSortKey','toPinyin','isArchiveFile','pinyinReady']);

const issues = [];
function walkNode(node, scopeChain) {
  if (!node || typeof node.type !== 'string') return;
  const isFn = ['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(node.type);
  let newScope = scopeChain;
  if (isFn) {
    const names = new Set();
    for (const p of node.params) collectPattern(p, names);
    const body = node.body.type === 'BlockStatement' ? node.body : null;
    if (body) collectDeclsInBody(body, names);
    newScope = [...scopeChain, names];
  }
  // 赋值目标检查（不含嵌套函数体，由其自身递归处理）
  if (node.type === 'AssignmentExpression') {
    if (node.left.type === 'Identifier' && node.operator === '=') {
      if (!resolve(node.left.name, newScope) && !KNOWN.has(node.left.name)) {
        issues.push(node.left.name);
      }
    }
  } else if (node.type === 'UpdateExpression' && node.argument.type === 'Identifier') {
    if (!resolve(node.argument.name, newScope) && !KNOWN.has(node.argument.name)) {
      issues.push(node.argument.name);
    }
  }
  for (const key of Object.keys(node)) {
    if (['start','end','loc','range','parent'].includes(key)) continue;
    const v = node[key];
    if (Array.isArray(v)) { for (const c of v) if (c && typeof c.type === 'string') walkNode(c, newScope); }
    else if (v && typeof v.type === 'string') {
      if (isFn && key === 'body') continue; // 函数体单独按新作用域处理
      walkNode(v, newScope);
    }
  }
  if (isFn && node.body) walkNode(node.body, newScope);
}
function collectDeclsInBody(body, out) {
  const stack = [body];
  while (stack.length) {
    const n = stack.pop();
    if (!n || typeof n.type !== 'string') continue;
    if (n !== body && ['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(n.type)) {
      if (n.type === 'FunctionDeclaration' && n.id) out.add(n.id.name);
      continue;
    }
    if (n.type === 'VariableDeclaration') { for (const d of n.declarations) collectPattern(d.id, out); }
    for (const k of Object.keys(n)) {
      if (['start','end','loc','range'].includes(k)) continue;
      const v = n[k];
      if (Array.isArray(v)) { for (const c of v) if (c && typeof c.type === 'string') stack.push(c); }
      else if (v && typeof v.type === 'string') stack.push(v);
    }
  }
}
function resolve(name, chain) {
  for (let i = chain.length - 1; i >= 0; i--) if (chain[i].has(name)) return true;
  return moduleNames.has(name);
}
walkNode(ast, []);
console.log('疑似隐式全局写:', [...new Set(issues)].join(', ') || '无');
