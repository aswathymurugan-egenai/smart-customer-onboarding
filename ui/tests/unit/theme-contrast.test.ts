import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

type Rgb = [number, number, number];

/** Pull `--name: oklch(...)` declarations out of the block that starts at `selector`. */
function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries(
    [...block.matchAll(/--([a-z-]+):\s*(oklch\([^)]*\))/g)].map((match) => [match[1], match[2]]),
  );
}

function oklchToRgb(value: string): Rgb {
  const [l, c, h] = value
    .replace(/oklch\(|\)/g, "")
    .split("/")[0]
    .trim()
    .split(/\s+/)
    .map(Number);
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l3 = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m3 = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s3 = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
    -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
    -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3,
  ].map((channel) => Math.min(1, Math.max(0, channel))) as Rgb;
}

function luminance([r, g, b]: Rgb): number {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(oklchToRgb(foreground)), luminance(oklchToRgb(background))].sort(
    (x, y) => y - x,
  );
  return (light + 0.05) / (dark + 0.05);
}

const TEXT_PAIRS: Array<[string, string]> = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["primary-foreground", "primary"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["primary", "background"],
  ["primary", "card"],
  ["destructive", "background"],
  ["destructive", "card"],
];

const BOUNDARY_PAIRS: Array<[string, string]> = [
  ["ring", "background"],
  ["ring", "card"],
  ["input", "background"],
  ["input", "card"],
];

describe.each([
  ["light", ":root"],
  ["dark", ".dark"],
])("%s theme contrast", (_name, selector) => {
  const theme = tokens(selector);

  it.each(TEXT_PAIRS)("%s on %s meets 4.5:1 for text", (foreground, background) => {
    expect(contrast(theme[foreground], theme[background])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(BOUNDARY_PAIRS)("%s against %s meets 3:1 for focus rings and input borders", (foreground, background) => {
    expect(contrast(theme[foreground], theme[background])).toBeGreaterThanOrEqual(3);
  });
});

describe("palette", () => {
  it("assigns the accent to the primary and ring tokens only", () => {
    for (const selector of [":root", ".dark"]) {
      const theme = tokens(selector);
      const chromatic = Object.entries(theme)
        .filter(([, value]) => Number(value.replace("oklch(", "").split(/\s+/)[1]) > 0)
        .map(([name]) => name)
        .sort();

      expect(chromatic).toEqual(["destructive", "primary", "ring"]);
      expect(theme.ring).toBe(theme.primary);
    }
  });
});
