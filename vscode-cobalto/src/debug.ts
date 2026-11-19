// Debugging: launch configuration, preparation with "cobalto debug" and the
// adapter factory (Cobalto's DAP proxy on top of lldb-dap).

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { CobaltoDapProxy } from './dap/proxy';
import { DapMessage } from './dap/protocol';
import { findLldbDap } from './dap/find-lldb';
import { CobaltoProject, pickProject, projectFor, readSuites, runCli } from './project';

export async function pickSuite(project?: CobaltoProject): Promise<string | undefined> {
  const p = project ?? (await pickProject());
  if (!p) {
    return undefined;
  }
  const { suites } = await readSuites(p);
  if (!suites.length) {
    vscode.window.showErrorMessage(`Cobalto: there are no suites in ${p.root} (patterns ${(p.config.tests ?? []).join(', ')}).`);
    return undefined;
  }
  const active = vscode.window.activeTextEditor?.document.uri.fsPath;
  const sorted = [...suites].sort((a, b) => (a.file === active ? -1 : b.file === active ? 1 : 0));
  const pick = await vscode.window.showQuickPick(
    sorted.map((s) => ({ label: s.id, description: s.description, detail: path.relative(p.root, s.file), id: s.id })),
    { placeHolder: 'Suite to debug' },
  );
  return pick?.id;
}

export class CobaltoConfigurationProvider implements vscode.DebugConfigurationProvider {
  constructor(private readonly output: vscode.OutputChannel) {}

  async provideDebugConfigurations(): Promise<vscode.DebugConfiguration[]> {
    return [
      { type: 'cobalto', request: 'launch', name: 'Cobalto: debug suite', suite: '${command:cobalto.pickSuite}', cwd: '${workspaceFolder}' },
    ];
  }

  async resolveDebugConfiguration(folder: vscode.WorkspaceFolder | undefined, config: vscode.DebugConfiguration): Promise<vscode.DebugConfiguration | undefined> {
    if (!config.type && !config.request && !config.name) {
      // F5 without launch.json: debug the active editor's suite or ask
      const project = await pickProject();
      if (!project) {
        return undefined;
      }
      const suite = await pickSuite(project);
      if (!suite) {
        return undefined;
      }
      config = { type: 'cobalto', request: 'launch', name: `Cobalto: debug ${suite}`, suite, cwd: project.root };
    }
    if (!config.cwd) {
      config.cwd = folder?.uri.fsPath ?? '${workspaceFolder}';
    }
    return config;
  }

  async resolveDebugConfigurationWithSubstitutedVariables(_folder: vscode.WorkspaceFolder | undefined, config: vscode.DebugConfiguration, token: vscode.CancellationToken): Promise<vscode.DebugConfiguration | undefined> {
    let project = config.cwd ? projectFor(String(config.cwd)) : undefined;
    if (!project) {
      project = await pickProject();
      if (!project) {
        return undefined;
      }
    }
    config.cwd = project.root;
    const build = project.config.build ?? 'build';
    if (!config.program) {
      config.program = path.join(project.root, build, 'cbltdrv');
    }
    const suite = typeof config.suite === 'string' && config.suite ? String(config.suite).toUpperCase() : undefined;
    config.suite = suite;
    if (config.prepare !== false) {
      if (!suite) {
        vscode.window.showErrorMessage('Cobalto: the configuration needs "suite" (or "prepare": false to use the last build).');
        return undefined;
      }
      this.output.show(true);
      const ok = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Cobalto: compiling ${suite} with -g (cobalto debug)`, cancellable: true },
        async (_p, t) => {
          const res = await runCli(project!, ['debug', '--suite', suite], this.output, undefined, t);
          return res.code === 0 && !t.isCancellationRequested && !token.isCancellationRequested;
        },
      );
      if (!ok) {
        vscode.window.showErrorMessage(`Cobalto: cobalto debug --suite ${suite} failed; check the Cobalto output channel.`);
        return undefined;
      }
    }
    if (!fs.existsSync(String(config.program))) {
      vscode.window.showErrorMessage(`Cobalto: the executable ${config.program} does not exist. Run cobalto debug --suite ${suite ?? 'X'}.`);
      return undefined;
    }
    const cfg = vscode.workspace.getConfiguration('cobalto');
    if (config.formatValues === undefined) {
      config.formatValues = cfg.get<boolean>('debug.formatValues', true);
    }
    return config;
  }
}

function resolveLldbDap(config: vscode.DebugConfiguration): string | undefined {
  const cfg = vscode.workspace.getConfiguration();
  return findLldbDap([
    typeof config.lldbDapPath === 'string' ? config.lldbDapPath : undefined,
    cfg.get<string>('cobalto.lldbDapPath') || undefined,
    cfg.get<string>('lldb-dap.executable-path') || undefined,
  ]);
}

/** Adapter in the extension host: the proxy talks to VS Code through messages. */
class InlineProxyAdapter implements vscode.DebugAdapter {
  private readonly emitter = new vscode.EventEmitter<vscode.DebugProtocolMessage>();
  readonly onDidSendMessage = this.emitter.event;
  private readonly proxy: CobaltoDapProxy;

  constructor(lldbDapPath: string, output: vscode.OutputChannel, formatValues: boolean, maxFormattedFields: number) {
    this.proxy = new CobaltoDapProxy((m) => this.emitter.fire(m as vscode.DebugProtocolMessage), {
      lldbDapPath,
      log: (s) => output.appendLine(`[dap] ${s}`),
      trace: !!process.env.COBALTO_DAP_LOG,
      formatValues,
      maxFormattedFields,
    });
  }

  handleMessage(message: vscode.DebugProtocolMessage): void {
    this.proxy.handleClientMessage(message as DapMessage);
  }

  dispose(): void {
    this.proxy.dispose();
    this.emitter.dispose();
  }
}

export class CobaltoAdapterFactory implements vscode.DebugAdapterDescriptorFactory {
  constructor(private readonly context: vscode.ExtensionContext, private readonly output: vscode.OutputChannel) {}

  createDebugAdapterDescriptor(session: vscode.DebugSession): vscode.ProviderResult<vscode.DebugAdapterDescriptor> {
    const lldb = resolveLldbDap(session.configuration);
    if (!lldb) {
      vscode.window.showErrorMessage('Cobalto: lldb-dap was not found. Install the Xcode command line tools or LLVM, or set the path in cobalto.lldbDapPath.');
      return undefined;
    }
    const cfg = vscode.workspace.getConfiguration('cobalto');
    const formatValues = session.configuration.formatValues !== false && cfg.get<boolean>('debug.formatValues', true);
    const maxFormatted = cfg.get<number>('debug.maxFormattedFields', 200);
    this.output.appendLine(`[dap] session ${session.name}: lldb-dap at ${lldb}`);
    if (cfg.get<string>('debug.adapterMode', 'inline') === 'process') {
      const script = this.context.asAbsolutePath(path.join('out', 'dap-proxy.js'));
      const args = [script, '--lldb-dap', lldb, '--log'];
      if (!formatValues) {
        args.push('--no-format');
      }
      return new vscode.DebugAdapterExecutable(process.execPath, args, { env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' } });
    }
    return new vscode.DebugAdapterInlineImplementation(new InlineProxyAdapter(lldb, this.output, formatValues, maxFormatted));
  }
}

/** "Cobalto: Debug suite" command. */
export async function debugSuiteCommand(uri?: vscode.Uri): Promise<void> {
  const project = await pickProject(uri);
  if (!project) {
    return;
  }
  let suite: string | undefined;
  if (uri && /\.(cblt|cbl)$/i.test(uri.fsPath)) {
    suite = (await readSuites(project)).suites.find((s) => s.file === uri.fsPath)?.id;
  }
  suite = suite ?? (await pickSuite(project));
  if (!suite) {
    return;
  }
  const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(project.root));
  await vscode.debug.startDebugging(folder, {
    type: 'cobalto',
    request: 'launch',
    name: `Cobalto: debug ${suite}`,
    suite,
    cwd: project.root,
  });
}
