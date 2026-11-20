import { useEffect, useRef, useState } from "react";

export function useWidth<T extends HTMLElement>(initial = 340) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const width = Math.floor(entries[0].contentRect.width);
      if (width > 0) setW(width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}
