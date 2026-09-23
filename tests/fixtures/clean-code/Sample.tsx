import { forwardRef, memo, useMemo } from "react";

interface Props {
  items: string[];
}

export function ItemList({ items }: Props) {
  const sorted = useMemo(() => [...items].sort(), [items]);
  return (
    <ul>
      {sorted.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export default function Page() {
  return <ItemList items={["b", "a"]} />;
}

export const Card = memo(function CardInner({ items }: Props) {
  return <ItemList items={items.map((item) => item.trim())} />;
});

export const Box = forwardRef<HTMLDivElement, Props>((props, ref) => <div ref={ref}>{props.items.length}</div>);

class Loader {
  load = (id: number): number => id + 1;
}
