import { describe, expect, it } from "vitest";
import { bollinger, ema, macd, rsi, sma } from "./indicators";

const rising = Array.from({ length: 40 }, (_, i) => 100 + i);
const flat = new Array(40).fill(50);

describe("indicators", () => {
  it("computes a simple moving average", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("seeds the EMA with the SMA of the first window", () => {
    // k = 0.5: 2 -> 4*0.5 + 2*0.5 = 3 -> 5*0.5 + 3*0.5 = 4
    expect(ema([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("collapses Bollinger Bands on a flat series and widens them on a moving one", () => {
    const bands = bollinger(flat, 20, 2);
    expect(bands.upper[25]).toBe(50);
    expect(bands.lower[25]).toBe(50);
    const moving = bollinger(rising, 20, 2);
    // population sd of 20 consecutive integers is sqrt((20^2 - 1) / 12)
    const sd = Math.sqrt((20 * 20 - 1) / 12);
    expect(moving.upper[19]).toBeCloseTo(109.5 + 2 * sd, 10);
    expect(moving.lower[19]).toBeCloseTo(109.5 - 2 * sd, 10);
  });

  it("gives RSI 100 for only gains, 0 for only losses and 50 for equal moves", () => {
    expect(rsi(rising, 14)[14]).toBe(100);
    expect(rsi([...rising].reverse(), 14)[20]).toBe(0);
    const zigzag = Array.from({ length: 30 }, (_, i) => (i % 2 ? 101 : 100));
    expect(rsi(zigzag, 14)[14]).toBeCloseTo(50, 10);
    expect(
      rsi(rising, 14)
        .slice(0, 14)
        .every((v) => v === null),
    ).toBe(true);
  });

  it("returns a zero MACD on a flat series and lines up the signal", () => {
    const result = macd(flat);
    expect(result.macd[25]).toBe(0);
    expect(result.macd[24]).toBeNull();
    expect(result.signal[33]).toBe(0);
    expect(result.signal[32]).toBeNull();
    expect(result.histogram[33]).toBe(0);
  });
});
