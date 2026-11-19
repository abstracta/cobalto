// Cobalto's VS Code extension: Test Explorer, coverage in the gutter,
// debugging with COBOL names and highlighting for the .cblt DSL.

import * as vscode from 'vscode';
import { CoverageDecorator } from './coverage';
import { CobaltoAdapterFactory, CobaltoConfigurationProvider, debugSuiteCommand, pickSuite } from './debug';
import { expressionAt, registerEvaluatableExpressionProviders } from './hover';
import { ProfileSelector } from './profile';
import { CobaltoTests } from './tests';

export interface CobaltoApi {
  tests: CobaltoTests;
  coverage: CoverageDecorator;
  profile: ProfileSelector;
  output: vscode.OutputChannel;
  /** COBOL name under a position (what the debug hover evaluates). */
  expressionAt: typeof expressionAt;
}

export function activate(context: vscode.ExtensionContext): CobaltoApi {
  const output = vscode.window.createOutputChannel('Cobalto');
  const coverage = new CoverageDecorator((text) => output.appendLine(text));
  const tests = new CobaltoTests(output, coverage);
  const profile = new ProfileSelector(() => tests.runAll());
  context.subscriptions.push(
    output,
    coverage,
    tests,
    profile,
    vscode.commands.registerCommand('cobalto.pickProfile', () => profile.pick()),
    vscode.debug.registerDebugConfigurationProvider('cobalto', new CobaltoConfigurationProvider(output)),
    vscode.debug.registerDebugAdapterDescriptorFactory('cobalto', new CobaltoAdapterFactory(context, output)),
    vscode.commands.registerCommand('cobalto.debugSuite', (uri?: vscode.Uri) => debugSuiteCommand(uri)),
    vscode.commands.registerCommand('cobalto.pickSuite', () => pickSuite()),
    vscode.commands.registerCommand('cobalto.runTests', () => tests.runAll()),
    vscode.commands.registerCommand('cobalto.refreshTests', () => tests.discover()),
    vscode.commands.registerCommand('cobalto.toggleCoverage', () => coverage.toggle()),
    registerEvaluatableExpressionProviders(),
  );
  void tests.discover();
  output.appendLine('Cobalto: extension active.');
  return { tests, coverage, profile, output, expressionAt };
}

export function deactivate(): void {
  /* nothing to clean up: everything is in context.subscriptions */
}
