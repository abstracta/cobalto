// Cobalto Test Explorer: a TestController that lists the suites (.cblt and
// legacy COBOL tests) with their TESTCASEs, runs "cobalto test --coverage" and
// reports the results from build/junit.xml per test case.

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { stopReason, wroteResults } from './cli-result';
import { CoverageDecorator, DetailedFileCoverage } from './coverage';
import { parseJunit } from './junit';
import { selectedProfile } from './profile';
import { CobaltoProject, findProjects, readSuites, runCli } from './project';
import { SuiteInfo } from './suites';

interface ItemData {
  kind: 'project' | 'suite' | 'case';
  project: CobaltoProject;
  suite?: SuiteInfo;
  caseName?: string;
}

export class CobaltoTests implements vscode.Disposable {
  readonly controller: vscode.TestController;
  private readonly data = new WeakMap<vscode.TestItem, ItemData>();
  private readonly disposables: vscode.Disposable[] = [];
  private running = false;
  /** number of the latest discovery: an older one that finishes later is dropped */
  private discovery = 0;
  private warnedNoCli = false;
  /** last state per item id (for verification and diagnostics) */
  readonly lastResults = new Map<string, string>();

  constructor(private readonly output: vscode.OutputChannel, private readonly coverage: CoverageDecorator) {
    this.controller = vscode.tests.createTestController('cobalto', 'Cobalto');
    this.controller.resolveHandler = async (item) => {
      if (!item) {
        await this.discover();
      }
    };
    this.controller.refreshHandler = async () => {
      await this.discover();
    };
    const runProfile = this.controller.createRunProfile('Run (cobalto test --coverage)', vscode.TestRunProfileKind.Run, (req, token) => this.run(req, token, false), true);
    const covProfile = this.controller.createRunProfile('Run with coverage', vscode.TestRunProfileKind.Coverage, (req, token) => this.run(req, token, true), true);
    covProfile.loadDetailedCoverage = async (_run, fc) => (fc instanceof DetailedFileCoverage ? fc.details : []);
    const watcher = vscode.workspace.createFileSystemWatcher('**/*.{cblt,cbl,CBL}');
    const rediscover = () => void this.discover();
    watcher.onDidChange(rediscover);
    watcher.onDidCreate(rediscover);
    watcher.onDidDelete(rediscover);
    this.disposables.push(this.controller, runProfile, covProfile, watcher);
  }

  async discover(): Promise<void> {
    const turn = ++this.discovery;
    const projects = await findProjects();
    const listings = await Promise.all(projects.map((p) => readSuites(p)));
    if (turn !== this.discovery) {
      return;
    }
    if (listings.some((l) => !l.ok) && !this.warnedNoCli) {
      this.warnedNoCli = true;
      vscode.window.showWarningMessage('Cobalto: the CLI did not list the suites. If it is not installed: python3 -m pip install cobalto, in a virtual environment in the project folder, or set cobalto.cliPath.');
    }
    this.controller.items.replace([]);
    const single = projects.length === 1;
    for (const [n, project] of projects.entries()) {
      const parent = single ? this.controller.items : this.projectItem(project).children;
      const { suites, errors } = listings[n];
      const items: vscode.TestItem[] = [];
      for (const e of errors) {
        // a file the CLI could not read stays visible, with its error
        const item = this.controller.createTestItem(`${project.root}::${e.file}`, path.basename(e.file), vscode.Uri.file(e.file));
        item.range = new vscode.Range(e.line - 1, 0, e.line - 1, 0);
        item.error = e.message;
        items.push(item);
      }
      for (const suite of suites) {
        const uri = vscode.Uri.file(suite.file);
        const item = this.controller.createTestItem(`${project.root}::${suite.id}`, suite.id, uri);
        item.description = suite.description;
        item.range = new vscode.Range(suite.line - 1, 0, suite.line - 1, 0);
        this.data.set(item, { kind: 'suite', project, suite });
        const seen = new Map<string, number>();
        for (const c of suite.cases) {
          const n = (seen.get(c.name) ?? 0) + 1;
          seen.set(c.name, n);
          const ci = this.controller.createTestItem(`${item.id}::${c.name}#${n}`, c.name, uri);
          ci.range = new vscode.Range(c.line - 1, 0, c.line - 1, 0);
          if (c.ignored) {
            ci.description = 'IGNORE';
            ci.tags = [new vscode.TestTag('ignored')];
          }
          this.data.set(ci, { kind: 'case', project, suite, caseName: c.name });
          item.children.add(ci);
        }
        items.push(item);
      }
      parent.replace(items);
    }
  }

  private projectItem(project: CobaltoProject): vscode.TestItem {
    const item = this.controller.createTestItem(project.root, path.basename(project.root), vscode.Uri.file(path.join(project.root, 'cblt.json')));
    this.data.set(item, { kind: 'project', project });
    this.controller.items.add(item);
    return item;
  }

  /** Waits for the run in progress to finish. */
  async whenIdle(): Promise<void> {
    while (this.running) {
      await new Promise((r) => setTimeout(r, 200));
    }
  }

  /** Runs every suite of every project (palette command). */
  async runAll(): Promise<void> {
    if (!this.controller.items.size) {
      await this.discover();
    }
    const req = new vscode.TestRunRequest();
    await this.run(req, new vscode.CancellationTokenSource().token, false);
  }

  /** Runs a single suite (what the "Run Test" button does on its node): cobalto test --coverage --filter SUITE. */
  async runSuite(label: string): Promise<void> {
    if (!this.controller.items.size) {
      await this.discover();
    }
    const item = [...this.controller.items].map(([, i]) => i).find((i) => i.label === label);
    if (!item) {
      throw new Error(`suite ${label} not found`);
    }
    await this.run(new vscode.TestRunRequest([item]), new vscode.CancellationTokenSource().token, false);
  }

  private async run(request: vscode.TestRunRequest, token: vscode.CancellationToken, withCoverage: boolean): Promise<void> {
    if (this.running) {
      vscode.window.showWarningMessage('Cobalto: a run is already in progress.');
      return;
    }
    this.running = true;
    const run = this.controller.createTestRun(request);
    try {
      const roots = request.include?.length ? request.include : [...this.controller.items].map(([, i]) => i);
      const excluded = new Set(request.exclude ?? []);
      // test cases to report and single suite (for --filter) per project
      const byProject = new Map<string, { project: CobaltoProject; suites: Set<string>; wholeProject: boolean; cases: vscode.TestItem[] }>();
      const collect = (item: vscode.TestItem, top: boolean) => {
        if (excluded.has(item)) {
          return;
        }
        const d = this.data.get(item);
        if (!d) {
          return;
        }
        let entry = byProject.get(d.project.root);
        if (!entry) {
          entry = { project: d.project, suites: new Set(), wholeProject: false, cases: [] };
          byProject.set(d.project.root, entry);
        }
        if (d.kind === 'project') {
          entry.wholeProject = true;
        } else if (d.kind === 'suite') {
          if (top) {
            entry.suites.add(d.suite!.id);
          }
          if (d.suite!.legacy) {
            entry.cases.push(item);
          }
        } else {
          entry.cases.push(item);
          if (top) {
            entry.suites.add(d.suite!.id);
          }
        }
        item.children.forEach((c) => collect(c, false));
      };
      for (const r of roots) {
        collect(r, true);
      }
      for (const entry of byProject.values()) {
        if (token.isCancellationRequested) {
          break;
        }
        for (const c of entry.cases) {
          run.enqueued(c);
        }
        const args = ['test', '--coverage'];
        const profile = selectedProfile();
        if (profile) {
          args.push('--profile', profile);
        }
        if (!entry.wholeProject && entry.suites.size === 1) {
          args.push('--filter', [...entry.suites][0]);
        }
        for (const c of entry.cases) {
          run.started(c);
        }
        run.appendOutput(`\r\n[${path.basename(entry.project.root)}] cobalto ${args.join(' ')}\r\n`);
        const res = await runCli(entry.project, args, this.output, (line) => run.appendOutput(line + '\r\n'), token);
        if (!wroteResults(res.code)) {
          // the CLI stopped before running the suites: build/ holds no results of this run
          const reason = stopReason(res.stderr) || 'check the output in the Cobalto channel';
          for (const c of entry.cases) {
            this.lastResults.set(c.id, 'errored');
            run.errored(c, new vscode.TestMessage(`cobalto ${args.join(' ')} did not run the suites (exit code ${res.code}).\n${reason}`));
          }
          this.coverage.invalidate();
          continue;
        }
        this.report(run, entry.project, entry.cases, res.code);
        if (withCoverage) {
          for (const fc of this.coverage.fileCoverages(entry.project)) {
            run.addCoverage(fc);
          }
        }
        this.coverage.invalidate();
      }
    } finally {
      run.end();
      this.running = false;
    }
  }

  private report(run: vscode.TestRun, project: CobaltoProject, cases: vscode.TestItem[], code: number | null): void {
    const junitPath = path.join(project.root, project.config.build ?? 'build', 'junit.xml');
    let xml: string;
    try {
      xml = fs.readFileSync(junitPath, 'utf8');
    } catch {
      for (const c of cases) {
        run.errored(c, new vscode.TestMessage(`${junitPath} was not found (cobalto exited with code ${code}). Check the output in the Cobalto channel.`));
      }
      return;
    }
    const results = parseJunit(xml);
    const index = new Map<string, (typeof results)[0]['cases']>();
    for (const s of results) {
      index.set(s.name, s.cases);
    }
    const used = new Map<string, number>();
    for (const item of cases) {
      const d = this.data.get(item)!;
      const suiteId = d.suite!.id;
      const name = d.kind === 'suite' ? suiteId : d.caseName!;
      const list = index.get(suiteId);
      if (!list) {
        run.errored(item, new vscode.TestMessage(`Suite ${suiteId} is not in junit.xml (did it compile? check the Cobalto channel).`));
        continue;
      }
      const key = `${suiteId}::${name}`;
      const nth = used.get(key) ?? 0;
      used.set(key, nth + 1);
      const matches = list.filter((c) => c.name === name);
      const r = matches[nth] ?? matches[0];
      if (!r) {
        run.errored(item, new vscode.TestMessage(`The test case is not in junit.xml: ${name}`));
        continue;
      }
      if (r.output) {
        run.appendOutput(r.output.replace(/\r?\n/g, '\r\n') + '\r\n', undefined, item);
      }
      this.lastResults.set(item.id, r.skipped ? 'skipped' : r.error ? 'errored' : r.failure ? 'failed' : 'passed');
      if (r.skipped) {
        run.skipped(item);
      } else if (r.error) {
        run.errored(item, new vscode.TestMessage(r.error));
      } else if (r.failure) {
        const msg = r.failure.expected !== undefined && r.failure.actual !== undefined
          ? vscode.TestMessage.diff(r.failure.text, r.failure.expected, r.failure.actual)
          : new vscode.TestMessage(r.failure.text);
        if (item.uri && item.range) {
          msg.location = new vscode.Location(item.uri, item.range);
        }
        run.failed(item, msg);
      } else {
        run.passed(item);
      }
    }
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
