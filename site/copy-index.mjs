import { cp, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "..");
const destination = resolve(repositoryRoot, "dist", "index");

await mkdir(destination, { recursive: true });
await cp(resolve(repositoryRoot, "index"), destination, { recursive: true });
