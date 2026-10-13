import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { randomBytes } from "crypto";
import { currentOwner, Docker, DockerUnavailableError, dockerRunner, processStartTime, type Owner } from "./docker.js";

describe("without a usable Docker", () => {
  it("reports a missing docker command as Docker not installed", async () => {
    const docker = new Docker({ runner: dockerRunner("/nonexistent/docker") });
    const error = await docker.listOwned().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(DockerUnavailableError);
    expect(String(error)).toContain("Docker is not installed");
  });

  it.skipIf(Bun.which("docker") === null)("reports a stopped daemon as Docker not running", async () => {
    const docker = new Docker({ runner: dockerRunner("docker", { ...process.env, DOCKER_HOST: "unix:///nonexistent/docker.sock" }) });
    const error = await docker.listOwned().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(DockerUnavailableError);
    expect(String(error)).toContain("Docker is not running");
  });
});

describe("process start time", () => {
  it("is the same text on every read of a live process, and undefined once it is gone", async () => {
    const own = await processStartTime(process.pid);
    expect(own).toMatch(/\d{4}$/);
    expect(await processStartTime(process.pid)).toBe(own);
    const child = Bun.spawn(["true"]);
    await child.exited;
    expect(await processStartTime(child.pid)).toBeUndefined();
  });
});

// Real Docker is required locally; a machine without it skips with the reason.
const dockerMissing = await new Docker()
  .listOwned()
  .then(() => undefined)
  .catch((e: unknown) => (e instanceof Error ? e.message : String(e)));
if (dockerMissing) console.warn(`Skipping Docker tests: ${dockerMissing}`);

const IMAGE = "busybox:1.37.0";

describe.skipIf(dockerMissing !== undefined)("owned containers on Docker", () => {
  // A label of its own, so nothing here can touch a real server's containers.
  const labelPrefix = `kedrzu.playwright-mcp-test-${randomBytes(4).toString("hex")}`;
  const docker = new Docker({ labelPrefix });

  beforeAll(async () => {
    if (!(await docker.hasImage(IMAGE))) await docker.pull(IMAGE, 120_000);
  }, 130_000);

  afterAll(async () => {
    await docker.remove((await docker.listOwned()).map((c) => c.name));
  });

  async function sleeper(name: string, owner: Owner): Promise<string> {
    const full = `${labelPrefix.replaceAll(".", "-")}-${name}`;
    await docker.start({ name: full, image: IMAGE, owner, command: ["sleep", "300"] });
    return full;
  }

  it("prunes containers whose owner is gone or whose PID was reused, and keeps a live owner's", async () => {
    const live = await currentOwner();
    const exited = Bun.spawn(["true"]);
    await exited.exited;
    const dead = await sleeper("dead", { pid: exited.pid, startTime: live.startTime });
    const reused = await sleeper("reused", { pid: process.pid, startTime: "Thu Jan 1 00:00:00 1970" });
    const kept = await sleeper("live", live);

    expect((await docker.pruneDeadOwners()).sort()).toEqual([dead, reused].sort());
    expect((await docker.listOwned()).map((c) => c.name)).toEqual([kept]);

    expect(await docker.removeOwnedBy(live)).toEqual([kept]);
    expect(await docker.listOwned()).toEqual([]);
  }, 60_000);
});
