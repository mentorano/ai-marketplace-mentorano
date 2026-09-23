"""Fixture for measure.py tests. Line numbers matter; do not reformat."""


def clean(a: int, b: int) -> int:
    return a + b


def complex_branches(x: int) -> str:
    if x == 1:
        return "one"
    elif x == 2:
        return "two"
    for i in range(x):
        if i % 2 and i % 3:
            continue
    while x > 100:
        x -= 1
    try:
        x = int("1")
    except ValueError:
        x = 0
    except TypeError:
        x = 1
    label = "big" if x > 10 else "small"
    fallback = x or 1
    squares = [n * n for n in range(fallback)]
    return f"{label}{squares}"


def too_many_params(a: int, b: int, c: int, d: int, e: int) -> int:
    return a + b + c + d + e


def deeply_nested(items: list[list[int]]) -> int:
    total = 0
    for row in items:
        for value in row:
            if value > 0:
                while value > 1:
                    value //= 2
                    total += 1
    return total


def long_function(n: int) -> list[int]:
    out: list[int] = []
    out.append(n + 1)
    out.append(n + 2)
    out.append(n + 3)
    out.append(n + 4)
    out.append(n + 5)
    out.append(n + 6)
    out.append(n + 7)
    out.append(n + 8)
    out.append(n + 9)
    out.append(n + 10)
    out.append(n + 11)
    out.append(n + 12)
    out.append(n + 13)
    out.append(n + 14)
    out.append(n + 15)
    out.append(n + 16)
    out.append(n + 17)
    out.append(n + 18)
    out.append(n + 19)
    out.append(n + 20)
    out.append(n + 21)
    out.append(n + 22)
    out.append(n + 23)
    out.append(n + 24)
    out.append(n + 25)
    out.append(n + 26)
    out.append(n + 27)
    out.append(n + 28)
    out.append(n + 29)
    out.append(n + 30)
    out.append(n + 31)
    out.append(n + 32)
    out.append(n + 33)
    out.append(n + 34)
    out.append(n + 35)
    out.append(n + 36)
    out.append(n + 37)
    out.append(n + 38)
    return out


class Widget:
    def method(self, a: int, b: int) -> int:  # noqa: D102
        return a + b  # type: ignore[no-any-return]

    def outer(self) -> int:
        def inner(v: int) -> int:
            if v:
                return 1
            return 0

        return inner(1)
