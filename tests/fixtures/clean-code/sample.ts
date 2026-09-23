// Fixture for measure.py tests. Line numbers matter; do not reformat.

export function clean(a: number, b: number): number {
  return a + b;
}

export function complexBranches(x: number): string {
  if (x === 1) {
    return "one";
  } else if (x === 2) {
    return "two";
  }
  for (let i = 0; i < x; i += 1) {
    if (i % 2 && i % 3) {
      continue;
    }
  }
  while (x > 100) {
    x -= 1;
  }
  try {
    x = Number.parseInt("1", 10);
  } catch {
    x = 0;
  }
  const label = x > 10 ? "big" : "small";
  const fallback = x || 1;
  const name = (undefined as string | undefined) ?? "n";
  switch (fallback) {
    case 1:
      return label + name;
    default:
      return label;
  }
}

export const tooManyParams = (a: number, b: number, c: number, d: number, e: number): number =>
  a + b + c + d + e;

export function deeplyNested(items: number[][]): number {
  let total = 0;
  for (const row of items) {
    for (const value of row) {
      if (value > 0) {
        let v = value;
        while (v > 1) {
          v = Math.floor(v / 2);
          total += 1;
        }
      }
    }
  }
  return total;
}

export function longFunction(n: number): number[] {
  const out: number[] = [];
  out.push(n + 1);
  out.push(n + 2);
  out.push(n + 3);
  out.push(n + 4);
  out.push(n + 5);
  out.push(n + 6);
  out.push(n + 7);
  out.push(n + 8);
  out.push(n + 9);
  out.push(n + 10);
  out.push(n + 11);
  out.push(n + 12);
  out.push(n + 13);
  out.push(n + 14);
  out.push(n + 15);
  out.push(n + 16);
  out.push(n + 17);
  out.push(n + 18);
  out.push(n + 19);
  out.push(n + 20);
  out.push(n + 21);
  out.push(n + 22);
  out.push(n + 23);
  out.push(n + 24);
  out.push(n + 25);
  out.push(n + 26);
  out.push(n + 27);
  out.push(n + 28);
  out.push(n + 29);
  out.push(n + 30);
  out.push(n + 31);
  out.push(n + 32);
  out.push(n + 33);
  out.push(n + 34);
  out.push(n + 35);
  out.push(n + 36);
  out.push(n + 37);
  out.push(n + 38);
  return out;
}

export class Widget {
  method(a: number, b: number): number {
    // eslint-disable-next-line no-console -- fixture
    console.log(a as any);
    return a + b;
  }

  outer(): number {
    const inner = (v: number): number => {
      if (v) {
        return 1;
      }
      return 0;
    };
    return inner(1) + [1, 2].map((n) => (n > 1 ? n : 0)).length;
  }
}
