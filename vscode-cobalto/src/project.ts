// Locating Cobalto projects (folders with a cblt.json) and running the CLI.

import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resolveCli } from './cli-path';
import { listingFrom, SuiteListing } from './suites';

export interface CobaltoProject {
  root: string;
  config: {
    tests?: string[];
    sources?: string[];
    build?: string;
    test_prefix?: string;
  };
}

export function readProject(root: string): CobaltoProject | undefined {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(root, 'cblt.json'), 'utf8'));
    return { root, config };
  } catch {
    return undefined;
  }
}

export async function findProjects(): Promise<CobaltoProject[]> {
  const files = await vscode.workspace.findFiles('**/cblt.json', '{**/node_modules/**,**/build/**,**/.git/**,**/.claude/**}', 50);
  const out: CobaltoProject[] = [];
  for (const f of files.sort((a, b) => a.fsPath.localeCompare(b.fsPath))) {
    const p = readProject(path.dirname(f.fsPath));
    if (p) {
      out.push(p);
    }
  }
  return out;
}

/** Project that contains a path (walking up until a cblt.json is found). */
export function projectFor(fsPath: string): CobaltoProject | undefined {
  let dir = fs.existsSync(fsPath) && fs.statSync(fsPath).isDirectory() ? fsPath : path.dirname(fsPath);
  for (;;) {
    if (fs.existsSync(path.join(dir, 'cblt.json'))) {
      return readProject(dir);
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
}

/** Picks the project: the active editor's, the only one there is, or asks. */
export async function pickProject(hint?: vscode.Uri): Promise<CobaltoProject | undefined> {
  const fromHint = hint ? projectFor(hint.fsPath) : undefined;
  if (fromHint) {
    return fromHint;
  }
  const active = vscode.window.activeTextEditor?.document.uri;
  const fromActive = active && active.scheme === 'file' ? projectFor(active.fsPath) : undefined;
  if (fromActive) {
    return fromActive;
  }
  const all = await findProjects();
  if (all.length === 1) {
    return all[0];
  }
  if (!all.length) {
    vscode.window.showErrorMessage('Cobalto: there is no cblt.json in the workspace.');
    return undefined;
  }
  const pick = await vscode.window.showQuickPick(
    all.map((p) => ({ label: path.basename(p.root), description: p.root, project: p })),
    { placeHolder: 'Cobalto project' },
  );
  return pick?.project;
}

export function cliCommand(project: CobaltoProject): string {
  return resolveCli(project.root, vscode.workspace.getConfiguration('cobalto').get<string>('cliPath') || '');
}

/**
 * Asks the CLI for data (a --json command), without echoing anything. The
 * document counts whatever the exit code is: a command that found errors
 * reports them in it. Undefined when the CLI did not answer with JSON.
 */
export function queryCli(project: CobaltoProject, args: string[]): Promise<unknown> {
  return new Promise((resolve) => {
    cp.execFile(cliCommand(project), args, { cwd: project.root, maxBuffer: 16 * 1024 * 1024, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }, (_error, stdout) => {
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve(undefined);
      }
    });
  });
}

/** The suites and test cases of a project, as the CLI reads them. */
export async function readSuites(project: CobaltoProject): Promise<SuiteListing> {
  return listingFrom(await queryCli(project, ['list', '--json']), project.root);
}

export interface RunResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

/** Runs the CLI with the given arguments, echoing the output to the channel. */
export function runCli(
  project: CobaltoProject,
  args: string[],
  output: vscode.OutputChannel,
  onLine?: (line: string) => void,
  token?: vscode.CancellationToken,
): Promise<RunResult> {
  const cli = cliCommand(project);
  output.appendLine(`$ ${cli} ${args.join(' ')}   (in ${project.root})`);
  return new Promise((resolve) => {
    const child = cp.spawn(cli, args, { cwd: project.root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    let stdout = '';
    let stderr = '';
    const feed = (chunk: Buffer, isErr: boolean) => {
      const text = chunk.toString('utf8');
      if (isErr) {
        stderr += text;
      } else {
        stdout += text;
      }
      output.append(text);
      if (onLine) {
        for (const line of text.split(/\r?\n/)) {
          if (line) {
            onLine(line);
          }
        }
      }
    };
    child.stdout.on('data', (c: Buffer) => feed(c, false));
    child.stderr.on('data', (c: Buffer) => feed(c, true));
    child.on('error', (e) => {
      output.appendLine(`could not run ${cli}: ${e.message}. Install the Cobalto CLI or set cobalto.cliPath.`);
      resolve({ code: -1, stdout, stderr: stderr + e.message });
    });
    child.on('close', (code) => resolve({ code, stdout, stderr }));
    token?.onCancellationRequested(() => child.kill());
  });
}
