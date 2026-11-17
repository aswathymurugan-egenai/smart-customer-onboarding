// The standalone server needs the static assets and public files beside it. Copying is
// idempotent, so a second build leaves the same result.
import { cpSync, existsSync } from "node:fs";

const standalone = ".next/standalone";
if (!existsSync(standalone)) {
  throw new Error("Run `next build` first: .next/standalone does not exist.");
}
cpSync(".next/static", `${standalone}/.next/static`, { recursive: true, force: true });
if (existsSync("public")) {
  cpSync("public", `${standalone}/public`, { recursive: true, force: true });
}
