import Decimal from 'decimal.js';

Decimal.set({ precision: 40, rounding: Decimal.ROUND_HALF_UP });

/**
 * Safe expression engine.
 * Grammar (recursive descent) — NO eval() / new Function() anywhere:
 *
 *   expr    := term (('+' | '-') term)*
 *   term    := factor (('*' | '/' | '%') factor)*
 *   factor  := ('-' | '+')? power
 *   power   := primary (('^' | '**') power)?
 *   primary := NUMBER | IDENT '(' args ')' | IDENT | '(' expr ')'
 *
 * Series-aware functions receive number[] and return number | number[].
 * The authoritative production engine is the Python Decimal implementation in
 * backend/app/domain/math_engine; this is its byte-compatible browser twin used
 * for the offline/PWA layer.
 */

export class MathEngineError extends Error {
  constructor(message: string, public position?: number) {
    super(message);
    this.name = 'MathEngineError';
  }
}

type Token =
  | { t: 'num'; v: number; pos: number }
  | { t: 'id'; v: string; pos: number }
  | { t: 'op'; v: string; pos: number };

const ALLOWED_FUNCTIONS = new Set([
  'abs',
  'min',
  'max',
  'mean',
  'sd',
  'rsd',
  'sum',
  'sqrt',
  'ln',
  'log10',
  'exp',
  'round',
  'ols_r2',
  'ols_slope',
  'ols_intercept',
  'rs_deviation',
  'pct_error',
  'count',
]);

export function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i++;
      continue;
    }
    if (/[0-9.]/.test(c)) {
      let j = i;
      while (j < src.length && /[0-9.]/.test(src[j])) j++;
      // exponent form 1e-3
      if (j < src.length && /[eE]/.test(src[j]) && /[0-9+-]/.test(src[j + 1] ?? '')) {
        j++;
        if (/[+-]/.test(src[j])) j++;
        while (j < src.length && /[0-9]/.test(src[j])) j++;
      }
      const raw = src.slice(i, j);
      const v = Number(raw);
      if (!Number.isFinite(v)) throw new MathEngineError(`رقم غير صالح: ${raw}`, i);
      tokens.push({ t: 'num', v, pos: i });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
      tokens.push({ t: 'id', v: src.slice(i, j), pos: i });
      i = j;
      continue;
    }
    // `**` must be tokenised before `*` so power binds as one operator
    if (c === '*' && src[i + 1] === '*') {
      tokens.push({ t: 'op', v: '**', pos: i });
      i += 2;
      continue;
    }
    if ('+-*/%^(),'.includes(c)) {
      tokens.push({ t: 'op', v: c, pos: i });
      i++;
      continue;
    }
    throw new MathEngineError(`رمز غير مسموح: "${c}"`, i);
  }
  return tokens;
}

export type Ast =
  | { k: 'num'; v: number }
  | { k: 'var'; name: string }
  | { k: 'bin'; op: string; a: Ast; b: Ast }
  | { k: 'neg'; a: Ast }
  | { k: 'call'; name: string; args: Ast[] };

export function parse(src: string): Ast {
  const tokens = tokenize(src);
  let p = 0;
  const peek = () => tokens[p];
  const eat = (v?: string) => {
    const tk = tokens[p];
    if (!tk) throw new MathEngineError('تعبير غير مكتمل');
    if (v && !(tk.t === 'op' && tk.v === v)) {
      throw new MathEngineError(`متوقع "${v}"`, tk.pos);
    }
    p++;
    return tk;
  };

  function expr(): Ast {
    let node = term();
    while (peek() && peek().t === 'op' && ['+', '-'].includes((peek() as any).v)) {
      const op = (eat() as any).v;
      node = { k: 'bin', op, a: node, b: term() };
    }
    return node;
  }
  function term(): Ast {
    let node = factor();
    while (peek() && peek().t === 'op' && ['*', '/', '%'].includes((peek() as any).v)) {
      const op = (eat() as any).v;
      node = { k: 'bin', op, a: node, b: factor() };
    }
    return node;
  }
  function factor(): Ast {
    if (peek() && peek().t === 'op' && ['-', '+'].includes((peek() as any).v)) {
      const op = (eat() as any).v;
      const a = factor();
      return op === '-' ? { k: 'neg', a } : a;
    }
    return power();
  }
  function power(): Ast {
    const base = primary();
    // both spellings are accepted: the Python blueprint writes `**`, the older
    // browser tables used `^`. They mean the same thing and must parse the same way.
    if (peek() && peek().t === 'op' && ['^', '**'].includes((peek() as any).v)) {
      eat();
      return { k: 'bin', op: '^', a: base, b: power() };
    }
    return base;
  }
  function primary(): Ast {
    const tk = peek();
    if (!tk) throw new MathEngineError('تعبير غير مكتمل');
    if (tk.t === 'num') {
      eat();
      return { k: 'num', v: tk.v };
    }
    if (tk.t === 'id') {
      eat();
      if (peek() && peek().t === 'op' && (peek() as any).v === '(') {
        eat('(');
        const args: Ast[] = [];
        if (!(peek() && peek().t === 'op' && (peek() as any).v === ')')) {
          args.push(expr());
          while (peek() && peek().t === 'op' && (peek() as any).v === ',') {
            eat(',');
            args.push(expr());
          }
        }
        eat(')');
        if (!ALLOWED_FUNCTIONS.has(tk.v)) {
          throw new MathEngineError(`دالة غير مسموحة: ${tk.v}`, tk.pos);
        }
        return { k: 'call', name: tk.v, args };
      }
      return { k: 'var', name: tk.v };
    }
    if (tk.t === 'op' && tk.v === '(') {
      eat('(');
      const e = expr();
      eat(')');
      return e;
    }
    throw new MathEngineError('بنية تعبير غير صالحة', tk.pos);
  }

  const ast = expr();
  if (p !== tokens.length) throw new MathEngineError('رموز زائدة في نهاية التعبير', tokens[p]?.pos);
  return ast;
}

/* ---------------------------- statistics helpers --------------------------- */

export function mean(xs: number[]): number {
  if (!xs.length) return NaN;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function sd(xs: number[]): number {
  if (xs.length < 2) return NaN;
  const m = mean(xs);
  const ss = xs.reduce((a, b) => a + (b - m) ** 2, 0);
  return Math.sqrt(ss / (xs.length - 1));
}

export function rsd(xs: number[]): number {
  const m = mean(xs);
  if (!m) return NaN;
  return (sd(xs) / m) * 100;
}

export function ols(xs: number[], ys: number[]) {
  const n = xs.length;
  if (n !== ys.length || n < 2) throw new MathEngineError('OLS: بيانات غير كافية أو أطوال غير متساوية');
  const mx = mean(xs);
  const my = mean(ys);
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (let i = 0; i < n; i++) {
    sxx += (xs[i] - mx) ** 2;
    sxy += (xs[i] - mx) * (ys[i] - my);
    syy += (ys[i] - my) ** 2;
  }
  const slope = sxy / sxx;
  const intercept = my - slope * mx;
  const ssRes = ys.reduce((acc, y, i) => acc + (y - (slope * xs[i] + intercept)) ** 2, 0);
  const r2 = syy === 0 ? 1 : 1 - ssRes / syy;
  const residuals = ys.map((y, i) => y - (slope * xs[i] + intercept));
  return { slope, intercept, r2, residuals };
}

/** Relative-sensitivity deviation used by Integrity Guide Ch.2 (detector linearity) */
export function rsDeviation(heights: number[], concs: number[]): number[] {
  if (heights.length !== concs.length || heights.length < 3) {
    throw new MathEngineError('rs_deviation: يتطلب 3 نقاط على الأقل');
  }
  const rs = heights.map((h, i) => h / concs[i]);
  const std = (rs[0] + rs[1] + rs[2]) / 3;
  return rs.map((r) => ((r - std) / std) * 100);
}

function toNum(v: number | number[]): number {
  if (Array.isArray(v)) throw new MathEngineError('هذه الدالة تتطلب قيمة مفردة');
  return v;
}
function toArr(v: number | number[]): number[] {
  if (!Array.isArray(v)) throw new MathEngineError('هذه الدالة تتطلب سلسلة قيم');
  if (!v.length) throw new MathEngineError('سلسلة قيم فارغة');
  return v;
}

const scalar =
  (fn: (x: number) => number) =>
  (args: (number | number[])[]): number | number[] => {
    const x = args[0];
    return Array.isArray(x) ? x.map(fn) : fn(x as number);
  };

const FN: Record<string, (args: (number | number[])[]) => number | number[]> = {
  abs: scalar(Math.abs),
  sqrt: scalar((x) => Math.sqrt(x)),
  ln: scalar((x) => Math.log(x)),
  log10: scalar((x) => Math.log10(x)),
  exp: scalar((x) => Math.exp(x)),
  round: (a) => {
    const x = toNum(a[0]);
    const d = a[1] === undefined ? 0 : toNum(a[1]);
    return Number(new Decimal(x).toDecimalPlaces(d, Decimal.ROUND_HALF_UP).toString());
  },
  min: (a) => Math.min(...a.flatMap((x) => (Array.isArray(x) ? x : [x]))),
  max: (a) => Math.max(...a.flatMap((x) => (Array.isArray(x) ? x : [x]))),
  sum: (a) => toArr(a[0]).reduce((p, c) => p + c, 0),
  mean: (a) => mean(toArr(a[0])),
  sd: (a) => sd(toArr(a[0])),
  rsd: (a) => rsd(toArr(a[0])),
  count: (a) => toArr(a[0]).length,
  ols_r2: (a) => ols(toArr(a[0]), toArr(a[1])).r2,
  ols_slope: (a) => ols(toArr(a[0]), toArr(a[1])).slope,
  ols_intercept: (a) => ols(toArr(a[0]), toArr(a[1])).intercept,
  rs_deviation: (a) => rsDeviation(toArr(a[0]), toArr(a[1])),
  pct_error: (a) => {
    const measured = toNum(a[0]);
    const reference = toNum(a[1]);
    if (reference === 0) throw new MathEngineError('pct_error: القيمة المرجعية صفر');
    return ((measured - reference) / reference) * 100;
  },
};

export function evaluate(ast: Ast, scope: Record<string, number | number[]>): number | number[] {
  switch (ast.k) {
    case 'num':
      return ast.v;
    case 'var': {
      if (!(ast.name in scope)) throw new MathEngineError(`متغير غير معروف: ${ast.name}`);
      return scope[ast.name];
    }
    case 'neg': {
      const v = evaluate(ast.a, scope);
      return Array.isArray(v) ? v.map((x) => -x) : -v;
    }
    case 'bin': {
      const a = evaluate(ast.a, scope);
      const b = evaluate(ast.b, scope);
      if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) throw new MathEngineError('عمليتان على سلسلتين بأطوال مختلفة');
        return a.map((x, i) => binop(ast.op, x, b[i]));
      }
      if (Array.isArray(a)) return a.map((x) => binop(ast.op, x, b as number));
      if (Array.isArray(b)) return b.map((x) => binop(ast.op, a as number, x));
      return binop(ast.op, a, b);
    }
    case 'call': {
      const fn = FN[ast.name];
      if (!fn) throw new MathEngineError(`دالة غير مسموحة: ${ast.name}`);
      return fn(ast.args.map((x) => evaluate(x, scope)));
    }
  }
}

function binop(op: string, a: number, b: number): number {
  switch (op) {
    case '+':
      return a + b;
    case '-':
      return a - b;
    case '*':
      return a * b;
    case '/':
      if (b === 0) throw new MathEngineError('قسمة على صفر');
      return a / b;
    case '%':
      if (b === 0) throw new MathEngineError('باقي قسمة على صفر');
      return a % b;
    case '^':
      return a ** b;
    default:
      throw new MathEngineError(`عامل غير معروف: ${op}`);
  }
}

export function evalExpression(src: string, scope: Record<string, number | number[]> = {}) {
  return evaluate(parse(src), scope);
}

/** Round strictly at the presentation boundary — storage keeps full precision. */
export function roundForDisplay(value: number, decimals: number): string {
  if (!Number.isFinite(value)) return '—';
  return new Decimal(value).toDecimalPlaces(decimals, Decimal.ROUND_HALF_UP).toFixed(decimals);
}
