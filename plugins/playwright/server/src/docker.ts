// A thin layer over the `docker` CLI for the VPN tunnel containers.
//
// Container environment never appears in argv: `docker run` gets `-e NAME` and the value travels
// in the docker process's own environment, so the proxy password and the control API key stay out
// of `ps`, of error messages and of logs. Docker does keep them in the container's config, where
// `docker inspect` shows them; they are random per container and die with it. A secret that
// outlives the container (the VPN login) goes in a read-only bind-mounted file instead.
//
// Every container is labelled with its owner's PID and that process's start time. A container
// whose owner is gone, or whose PID now belongs to another process, is an orphan any server may
// remove.

import type { Env } from "./config.js";

export const LABEL_PREFIX = "kedrzu.playwright-mcp";

export interface DockerCall {
  args: string[];
  // Added to the docker process's environment; how container env values reach `-e NAME`.
  env: Record<string, string>;
  timeoutMs?: number;
}

export interface DockerOutput {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export type DockerRunner = (call: DockerCall) => Promise<DockerOutput>;

// Docker cannot be used at all: not installed, or the daemon is not running.
export class DockerUnavailableError extends Error {}

export class DockerTimeoutError extends Error {}

export class DockerCommandError extends Error {
  constructor(
    message: string,
    readonly output: DockerOutput
  ) {
    super(message);
  }
}

export interface Owner {
  pid: number;
  startTime: string;
}

export interface ContainerSpec {
  // Omitted for throwaway `--rm` containers.
  name?: string;
  image: string;
  owner: Owner;
  // Passed by name only; see the header.
  env?: Record<string, string>;
  // Container ports, each published on a random host port of 127.0.0.1.
  publish?: number[];
  // Named volume → mount path.
  volumes?: Record<string, string>;
  // Host path → mount path, read-only.
  binds?: Record<string, string>;
  capAdd?: string[];
  devices?: string[];
  entrypoint?: string;
  command?: string[];
}

export interface PublishedPort {
  containerPort: number;
  hostIp: string;
  hostPort: number;
}

export interface ContainerState {
  running: boolean;
  exitCode: number;
  // The image's healthcheck: "starting", "healthy", "unhealthy"; undefined without one.
  health: string | undefined;
  ports: PublishedPort[];
}

export interface OwnedContainer {
  name: string;
  owner: Owner;
}

export function dockerRunner(command = "docker", baseEnv: Env = process.env): DockerRunner {
  return async ({ args, env, timeoutMs }) => {
    let proc: Bun.Subprocess<"ignore", "pipe", "pipe">;
    try {
      proc = Bun.spawn([command, ...args], { env: { ...baseEnv, ...env }, stdin: "ignore", stdout: "pipe", stderr: "pipe" });
    } catch (e) {
      if (e instanceof Error && "code" in e && e.code === "ENOENT") {
        throw new DockerUnavailableError(`Docker is not installed: the \`${command}\` command was not found. VPN regions need Docker.`);
      }
      throw e;
    }
    let timedOut = false;
    const timer =
      timeoutMs === undefined
        ? undefined
        : setTimeout(() => {
            timedOut = true;
            proc.kill("SIGKILL");
          }, timeoutMs);
    try {
      const [stdout, stderr, exitCode] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text(), proc.exited]);
      if (timedOut) throw new DockerTimeoutError(`docker ${args[0]} did not finish within ${formatDuration(timeoutMs ?? 0)}`);
      return { exitCode, stdout, stderr };
    } finally {
      clearTimeout(timer);
    }
  };
}

export function formatDuration(ms: number): string {
  return ms >= 60_000 && ms % 60_000 === 0 ? `${ms / 60_000} min` : `${Math.round(ms / 1000)} s`;
}

// `ps -o lstart=` in a fixed time zone and locale, so every server writes and compares the same
// text for the same process whatever its own TZ. Undefined when no such process exists.
export async function processStartTime(pid: number): Promise<string | undefined> {
  const proc = Bun.spawn(["ps", "-o", "lstart=", "-p", String(pid)], {
    env: { ...process.env, TZ: "UTC", LC_ALL: "C" },
    stdin: "ignore",
    stdout: "pipe",
    stderr: "ignore",
  });
  const [stdout, exitCode] = await Promise.all([new Response(proc.stdout).text(), proc.exited]);
  const startTime = stdout.trim().replace(/\s+/g, " ");
  return exitCode === 0 && startTime ? startTime : undefined;
}

export async function currentOwner(): Promise<Owner> {
  const startTime = await processStartTime(process.pid);
  if (!startTime) throw new Error(`Cannot read the start time of this process (${process.pid}) with ps`);
  return { pid: process.pid, startTime };
}

export class Docker {
  private readonly runner: DockerRunner;
  readonly ownerLabel: string;
  readonly ownerStartLabel: string;

  constructor(options: { runner?: DockerRunner; labelPrefix?: string } = {}) {
    this.runner = options.runner ?? dockerRunner();
    const prefix = options.labelPrefix ?? LABEL_PREFIX;
    this.ownerLabel = `${prefix}.owner`;
    this.ownerStartLabel = `${prefix}.owner-start`;
  }

  // `docker run -d`.
  async start(spec: ContainerSpec): Promise<void> {
    await this.exec(["run", "-d", ...this.runArgs(spec)], { env: spec.env });
  }

  // `docker run --rm`, attached; a non-zero exit is the caller's to interpret.
  async runToCompletion(spec: ContainerSpec, timeoutMs: number): Promise<DockerOutput> {
    return this.exec(["run", "--rm", ...this.runArgs(spec)], { env: spec.env, timeoutMs, check: false });
  }

  async inspect(name: string): Promise<ContainerState | undefined> {
    const output = await this.exec(["inspect", "--type", "container", "--format", "{{json .State}}\t{{json .NetworkSettings.Ports}}", name], {
      check: false,
    });
    if (output.exitCode !== 0) {
      if (/no such (container|object)/i.test(output.stderr)) return undefined;
      throw commandError("inspect", output);
    }
    const [state, ports] = output.stdout.trim().split("\t");
    return parseState(JSON.parse(state), JSON.parse(ports));
  }

  // stdout and stderr together; gluetun writes its log to both.
  async logs(name: string, tail = 500): Promise<string> {
    const output = await this.exec(["logs", "--tail", String(tail), name]);
    return `${output.stdout}\n${output.stderr}`;
  }

  async remove(names: string[]): Promise<void> {
    if (!names.length) return;
    const output = await this.exec(["rm", "-f", ...names], { check: false });
    // Already gone, or going because someone else removes it, is what we wanted.
    const unexpected = output.stderr.split("\n").filter((line) => line.trim() && !/no such container|already in progress/i.test(line));
    if (output.exitCode !== 0 && (unexpected.length || !output.stderr.trim())) throw commandError("rm", output);
  }

  // Until the container stops or is gone; false when the time ran out first.
  async wait(name: string, timeoutMs: number): Promise<boolean> {
    try {
      await this.exec(["wait", name], { timeoutMs, check: false });
      return true;
    } catch (e) {
      if (e instanceof DockerTimeoutError) return false;
      throw e;
    }
  }

  async hasImage(image: string): Promise<boolean> {
    const output = await this.exec(["image", "inspect", "--format", "{{.Id}}", image], { check: false });
    return output.exitCode === 0;
  }

  async pull(image: string, timeoutMs: number): Promise<void> {
    await this.exec(["pull", "--quiet", image], { timeoutMs });
  }

  async listOwned(owner?: Owner): Promise<OwnedContainer[]> {
    const filter = owner ? `label=${this.ownerLabel}=${owner.pid}` : `label=${this.ownerLabel}`;
    const format = `{{.Names}}\t{{.Label "${this.ownerLabel}"}}\t{{.Label "${this.ownerStartLabel}"}}`;
    const output = await this.exec(["ps", "-a", "--filter", filter, "--format", format]);
    return output.stdout
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => {
        const [name, pid, startTime = ""] = line.split("\t");
        return { name, owner: { pid: Number(pid), startTime } };
      })
      .filter((c) => !owner || c.owner.startTime === owner.startTime);
  }

  // Removes `owner`'s containers; returns their names.
  async removeOwnedBy(owner: Owner): Promise<string[]> {
    const names = (await this.listOwned(owner)).map((c) => c.name);
    await this.remove(names);
    return names;
  }

  // Removes the containers whose owner process is no longer running; returns their names.
  async pruneDeadOwners(startTimeOf: (pid: number) => Promise<string | undefined> = processStartTime): Promise<string[]> {
    const containers = await this.listOwned();
    const alive = new Map<number, string | undefined>();
    const orphans: string[] = [];
    for (const { name, owner } of containers) {
      if (!alive.has(owner.pid)) alive.set(owner.pid, Number.isInteger(owner.pid) && owner.pid > 0 ? await startTimeOf(owner.pid) : undefined);
      if (alive.get(owner.pid) !== owner.startTime) orphans.push(name);
    }
    await this.remove(orphans);
    return orphans;
  }

  private runArgs(spec: ContainerSpec): string[] {
    const args: string[] = [];
    if (spec.name) args.push("--name", spec.name);
    args.push("--label", `${this.ownerLabel}=${spec.owner.pid}`, "--label", `${this.ownerStartLabel}=${spec.owner.startTime}`);
    for (const cap of spec.capAdd ?? []) args.push("--cap-add", cap);
    for (const device of spec.devices ?? []) args.push("--device", device);
    for (const port of spec.publish ?? []) args.push("-p", `127.0.0.1::${port}`);
    for (const [volume, target] of Object.entries(spec.volumes ?? {})) args.push("-v", `${volume}:${target}`);
    for (const [source, target] of Object.entries(spec.binds ?? {})) args.push("--mount", `type=bind,source=${source},target=${target},readonly`);
    for (const name of Object.keys(spec.env ?? {})) args.push("-e", name);
    if (spec.entrypoint) args.push("--entrypoint", spec.entrypoint);
    args.push(spec.image, ...(spec.command ?? []));
    return args;
  }

  private async exec(args: string[], options: { env?: Record<string, string>; timeoutMs?: number; check?: boolean } = {}): Promise<DockerOutput> {
    const output = await this.runner({ args, env: options.env ?? {}, timeoutMs: options.timeoutMs });
    if (output.exitCode !== 0 && /Cannot connect to the Docker daemon|failed to connect to the docker API|error during connect/i.test(output.stderr)) {
      throw new DockerUnavailableError(`Docker is not running (${firstLine(output.stderr)}). Start Docker to use VPN regions.`);
    }
    if ((options.check ?? true) && output.exitCode !== 0) throw commandError(args[0], output);
    return output;
  }
}

// Names the subcommand only: the rest of argv is not the reader's business.
function commandError(subcommand: string, output: DockerOutput): DockerCommandError {
  return new DockerCommandError(`docker ${subcommand} failed: ${firstLine(output.stderr) || `exit code ${output.exitCode}`}`, output);
}

export function firstLine(text: string): string {
  return (
    text
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean) ?? ""
  );
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseState(state: unknown, ports: unknown): ContainerState {
  if (!isRecord(state)) throw new Error("docker inspect returned no container state");
  const health = isRecord(state.Health) && typeof state.Health.Status === "string" ? state.Health.Status : undefined;
  const published: PublishedPort[] = [];
  if (isRecord(ports)) {
    for (const [key, bindings] of Object.entries(ports)) {
      if (!Array.isArray(bindings)) continue;
      for (const binding of bindings) {
        if (!isRecord(binding)) continue;
        published.push({ containerPort: parseInt(key, 10), hostIp: String(binding.HostIp ?? ""), hostPort: Number(binding.HostPort) });
      }
    }
  }
  return {
    running: state.Running === true,
    exitCode: typeof state.ExitCode === "number" ? state.ExitCode : -1,
    health,
    ports: published,
  };
}
