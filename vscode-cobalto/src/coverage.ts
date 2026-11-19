// Coverage in the gutter from build/lcov.info: executed and non-executed
// lines per statement, and entries per paragraph (FNDA). It also feeds
// VS Code's test coverage API (the "Coverage" profile).

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { BranchLabels, branchLabelsFrom } from './cov-map';
import { parseLcov, LcovFile } from './lcov';
import { CobaltoProject, projectFor } from './project';

type MarginMode = 'cobalto' | 'entriesOnly' | 'off';

const COVERAGE_GUTTERS = 'ryanluker.vscode-coverage-gutters';

export class CoverageDecorator implements vscode.Disposable {
  private enabled: boolean;
  private covered!: vscode.TextEditorDecorationType;
  private uncovered!: vscode.TextEditorDecorationType;
  private entries!: vscode.TextEditorDecorationType;
  private readonly status: vscode.StatusBarItem;
  private readonly cache = new Map<string, { mtime: number; files: LcovFile[] }>();
  private readonly disposables: vscode.Disposable[] = [];
  private readonly reported = new Set<string>();

  constructor(private readonly log: (text: string) => void = () => undefined) {
    this.enabled = vscode.workspace.getConfiguration('cobalto').get<boolean>('coverage.showOnStart', false);
    this.createDecorations();
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    this.status.command = 'cobalto.toggleCoverage';
    this.status.tooltip = 'Cobalto: show or hide coverage in the gutter';
    this.disposables.push(
      vscode.window.onDidChangeVisibleTextEditors(() => this.refresh()),
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (this.enabled && vscode.window.visibleTextEditors.some((ed) => ed.document === e.document)) {
          this.refresh();
        }
      }),
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('cobalto.coverage')) {
          this.createDecorations();
          this.refresh();
        }
      }),
      vscode.extensions.onDidChange(() => this.refresh()),
    );
    this.refresh();
  }

  /**
   * What Cobalto draws in the gutter. "auto" (the default) is everything, unless
   * Coverage Gutters is installed: then it leaves line highlighting to that
   * extension and keeps the entries per paragraph and the status bar.
   */
  marginMode(): MarginMode {
    const cfg = vscode.workspace.getConfiguration('cobalto').get<string>('coverage.margin', 'auto');
    if (cfg === 'cobalto' || cfg === 'entriesOnly' || cfg === 'off') {
      return cfg;
    }
    return vscode.extensions.getExtension(COVERAGE_GUTTERS) ? 'entriesOnly' : 'cobalto';
  }

  private createDecorations(): void {
    this.covered?.dispose();
    this.uncovered?.dispose();
    this.entries?.dispose();
    const cfg = vscode.workspace.getConfiguration('cobalto');
    const line = (background: string, ruler: string) => vscode.window.createTextEditorDecorationType({
      isWholeLine: true,
      backgroundColor: background,
      overviewRulerColor: new vscode.ThemeColor(ruler),
      overviewRulerLane: vscode.OverviewRulerLane.Left,
      borderWidth: '0 0 0 3px',
      borderStyle: 'solid',
      borderColor: new vscode.ThemeColor(ruler),
    });
    this.covered = line(cfg.get<string>('coverage.colors.covered', 'rgba(166, 220, 142, 0.45)'), 'testing.iconPassed');
    this.uncovered = line(cfg.get<string>('coverage.colors.uncovered', 'rgba(255, 88, 88, 0.45)'), 'testing.iconFailed');
    this.entries = vscode.window.createTextEditorDecorationType({
      after: { color: new vscode.ThemeColor('editorCodeLens.foreground'), margin: '0 0 0 2em', fontStyle: 'italic' },
    });
  }

  toggle(): void {
    if (this.marginMode() === 'off') {
      vscode.window.showInformationMessage('Cobalto: coverage in the gutter is turned off by the cobalto.coverage.margin setting.');
      return;
    }
    this.enabled = !this.enabled;
    this.refresh();
    if (this.enabled) {
      const shown = vscode.window.visibleTextEditors.filter((e) => this.lcovFor(e.document.uri.fsPath)).length;
      if (!shown) {
        vscode.window.showInformationMessage('Cobalto: coverage in the gutter is on, but there is no coverage for the open editors. Run the suites (cobalto test --coverage) and open a program under src/.');
      } else {
        const mode = this.marginMode() === 'entriesOnly' ? ' (entries per paragraph; Coverage Gutters highlights the lines)' : '';
        vscode.window.setStatusBarMessage(`Cobalto: coverage in the gutter on${mode}`, 4000);
      }
    } else {
      vscode.window.setStatusBarMessage('Cobalto: coverage in the gutter off', 4000);
    }
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  /** Reads lcov.info again (after a run) and redraws. */
  invalidate(): void {
    this.cache.clear();
    this.refresh();
  }

  private loadProject(project: CobaltoProject): LcovFile[] {
    const lcov = path.join(project.root, project.config.build ?? 'build', 'lcov.info');
    let mtime: number;
    try {
      mtime = fs.statSync(lcov).mtimeMs;
    } catch {
      return [];
    }
    const c = this.cache.get(project.root);
    if (c && c.mtime === mtime) {
      return c.files;
    }
    let files: LcovFile[];
    try {
      files = parseLcov(fs.readFileSync(lcov, 'utf8'));
    } catch {
      files = [];
    }
    this.cache.set(project.root, { mtime, files });
    return files;
  }

  lcovFor(fsPath: string): { project: CobaltoProject; file: LcovFile } | undefined {
    const project = projectFor(fsPath);
    if (!project) {
      return undefined;
    }
    const files = this.loadProject(project);
    const rel = path.relative(project.root, fsPath).split(path.sep).join('/');
    const file = files.find((f) => f.path === rel || path.resolve(project.root, f.path) === fsPath);
    return file ? { project, file } : undefined;
  }

  refresh(): void {
    for (const editor of vscode.window.visibleTextEditors) {
      this.decorate(editor);
    }
    this.updateStatus();
  }

  private updateStatus(): void {
    if (this.marginMode() === 'off') {
      this.status.hide();
      return;
    }
    const active = vscode.window.activeTextEditor;
    const hit = active && active.document.uri.scheme === 'file' ? this.lcovFor(active.document.uri.fsPath) : undefined;
    if (!hit && !this.enabled) {
      this.status.hide();
      return;
    }
    if (hit) {
      const total = hit.file.lines.size;
      const covered = [...hit.file.lines.values()].filter((h) => h > 0).length;
      const br = hit.file.branches;
      const branches = br.length ? `, ${br.filter((b) => b.taken > 0).length}/${br.length} branches` : '';
      this.status.text = `$(${this.enabled ? 'eye' : 'eye-closed'}) Cobalto ${covered}/${total} statements${branches}`;
    } else {
      this.status.text = `$(eye) Cobalto: coverage`;
    }
    this.status.show();
  }

  private decorate(editor: vscode.TextEditor): void {
    const mode = this.marginMode();
    if (!this.enabled || mode === 'off' || editor.document.uri.scheme !== 'file') {
      editor.setDecorations(this.covered, []);
      editor.setDecorations(this.uncovered, []);
      editor.setDecorations(this.entries, []);
      return;
    }
    const hit = this.lcovFor(editor.document.uri.fsPath);
    if (!hit) {
      editor.setDecorations(this.covered, []);
      editor.setDecorations(this.uncovered, []);
      editor.setDecorations(this.entries, []);
      return;
    }
    const covered: vscode.Range[] = [];
    const uncovered: vscode.Range[] = [];
    const last = editor.document.lineCount - 1;
    for (const [line, hits] of hit.file.lines) {
      const l = Math.min(line - 1, last);
      const range = editor.document.lineAt(l).range;
      (hits > 0 ? covered : uncovered).push(range);
    }
    const entries: vscode.DecorationOptions[] = hit.file.functions.map((fn) => {
      const l = Math.min(fn.line - 1, last);
      const range = editor.document.lineAt(l).range;
      const text = fn.hits === 0 ? 'paragraph not executed' : fn.hits === 1 ? '1 entry' : `${fn.hits} entries`;
      return { range, renderOptions: { after: { contentText: text } }, hoverMessage: `Cobalto: ${fn.name}, ${text}` };
    });
    editor.setDecorations(this.covered, mode === 'cobalto' ? covered : []);
    editor.setDecorations(this.uncovered, mode === 'cobalto' ? uncovered : []);
    editor.setDecorations(this.entries, entries);
  }

  /**
   * Branch labels (THEN, ELSE, WHEN ..., operand true/false) and each
   * branch's own line, from build/cov/map.json, by file and by
   * "statement index:ordinal", which is how BRDA numbers them.
   */
  private branchLabels(project: CobaltoProject): BranchLabels {
    const mapPath = path.join(project.root, project.config.build ?? 'build', 'cov', 'map.json');
    let data: unknown;
    try {
      data = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
    } catch {
      return new Map();
    }
    const { labels, problem } = branchLabelsFrom(data, mapPath);
    if (problem && !this.reported.has(problem)) {
      // without the map the branches still show, numbered instead of labeled
      this.reported.add(problem);
      this.log(problem);
    }
    return labels;
  }

  /** Coverage for VS Code's test API (Coverage profile). */
  fileCoverages(project: CobaltoProject): DetailedFileCoverage[] {
    this.cache.delete(project.root);
    const labels = this.branchLabels(project);
    return this.loadProject(project).map((f) => {
      const uri = vscode.Uri.file(path.resolve(project.root, f.path));
      const details: vscode.FileCoverageDetail[] = [];
      const byLine = new Map<number, vscode.BranchCoverage[]>();
      for (const b of f.branches) {
        const info = labels.get(f.path)?.get(`${b.stmt}:${b.ordinal}`);
        const line = info?.line ?? b.line;
        const list = byLine.get(b.line) ?? [];
        list.push(new vscode.BranchCoverage(b.taken, new vscode.Position(line - 1, 0), info?.label ?? `branch ${b.ordinal + 1}`));
        byLine.set(b.line, list);
      }
      for (const [line, hits] of f.lines) {
        details.push(new vscode.StatementCoverage(hits, new vscode.Position(line - 1, 0), byLine.get(line)));
      }
      for (const fn of f.functions) {
        details.push(new vscode.DeclarationCoverage(fn.name, fn.hits, new vscode.Position(fn.line - 1, 0)));
      }
      const stmts = [...f.lines.values()];
      const fc = new DetailedFileCoverage(
        uri,
        new vscode.TestCoverageCount(stmts.filter((h) => h > 0).length, stmts.length),
        f.branches.length ? new vscode.TestCoverageCount(f.branches.filter((b) => b.taken > 0).length, f.branches.length) : undefined,
        f.functions.length ? new vscode.TestCoverageCount(f.functions.filter((x) => x.hits > 0).length, f.functions.length) : undefined,
      );
      fc.details = details;
      return fc;
    });
  }

  dispose(): void {
    this.covered.dispose();
    this.uncovered.dispose();
    this.entries.dispose();
    this.status.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}

export class DetailedFileCoverage extends vscode.FileCoverage {
  details: vscode.FileCoverageDetail[] = [];
}
