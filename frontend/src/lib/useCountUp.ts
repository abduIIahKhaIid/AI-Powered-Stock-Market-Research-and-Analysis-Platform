import { useEffect, useRef, useState } from "react";

/** Animates a number from its previous value to `target` (used for prices and KPIs). */
export function useCountUp(target: number, enabled: boolean, duration = 900): number {
  const [value, setValue] = useState(0);
  const from = useRef(0);

  useEffect(() => {
    if (!enabled || !Number.isFinite(target)) return;
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (time: number) => {
      const t = Math.min(1, (time - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      setValue(origin + (target - origin) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      from.current = target;
    };
  }, [target, enabled, duration]);

  return enabled ? value : target;
}
