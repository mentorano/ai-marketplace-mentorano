// Fixture for tests/test_measure_js.py. Line numbers and counts are asserted there.
"use strict";

function clean(a, b) {
  return a + b;
}

const tooManyParams = (a, b, c, d) => a + b + c + d;

function complexBranches(x) {
  if (x > 0 && x < 10) {
    return 1;
  } else if (x === 20 || x === 30) {
    return 2;
  }
  for (const i of [1, 2]) {
    if (i === x) return i;
  }
  return x > 100 ? 3 : (x ?? 0);
}

class Widget {
  constructor(name) {
    this.name = name;
  }

  label(prefix) {
    return [1, 2].map((n) => (n > 1 ? prefix + n : this.name));
  }
}

(function () {
  // eslint-disable-next-line no-console
  console.log("the same as any other script");
  function inner() {
    return 1;
  }
  inner();
})();

module.exports = { clean, tooManyParams, complexBranches, Widget };
