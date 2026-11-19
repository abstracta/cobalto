// Build profile the Test Explorer runs with: a setting, a command to choose
// it from a list and an item in the status bar. Empty: the project's default
// profile. The list comes from the CLI (cobalto profiles --json): the
// built-in profiles plus the ones the project adds in cblt.json.

import * as vscode from 'vscode';
import { CobaltoProject, findProjects, queryCli } from './project';

interface ProfileInfo {
  name: string;
  description: string;
}

export function selectedProfile(): string {
  return vscode.workspace.getConfiguration('cobalto').get<string>('profile', '').trim();
}

export async function readProfiles(project: CobaltoProject): Promise<{ defaultProfile: string; profiles: ProfileInfo[] }> {
  const doc = (await queryCli(project, ['profiles', '--json'])) as { default?: string; profiles?: ProfileInfo[] } | undefined;
  return { defaultProfile: doc?.default ?? '', profiles: doc?.profiles ?? [] };
}

export class ProfileSelector implements vscode.Disposable {
  private readonly status: vscode.StatusBarItem;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(private readonly runAll: () => Promise<void>) {
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 40);
    this.status.command = 'cobalto.pickProfile';
    this.disposables.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('cobalto.profile')) {
          void this.refresh();
        }
      }),
    );
    void this.refresh();
  }

  async refresh(): Promise<void> {
    const projects = await findProjects();
    if (!projects.length) {
      this.status.hide();
      return;
    }
    const chosen = selectedProfile();
    const { defaultProfile } = await readProfiles(projects[0]);
    const shown = chosen || defaultProfile;
    this.status.text = `$(tools) Cobalto: ${shown || 'profile'}`;
    this.status.tooltip = chosen
      ? `Cobalto: the suites run with the ${chosen} profile (cobalto.profile). Click to change it.`
      : `Cobalto: the suites run with the project's default profile (${defaultProfile}). Click to choose another compiler.`;
    this.status.show();
  }

  /** "Cobalto: Choose the compiler (cblt.json profile)" command. */
  async pick(): Promise<void> {
    const projects = await findProjects();
    if (!projects.length) {
      vscode.window.showWarningMessage('Cobalto: there is no cblt.json in the workspace.');
      return;
    }
    const { defaultProfile, profiles } = await readProfiles(projects[0]);
    const current = selectedProfile();
    const items: (vscode.QuickPickItem & { value: string })[] = [
      { label: `$(home) project default (${defaultProfile})`, description: current ? '' : 'current', value: '' },
      ...profiles.map((p) => ({
        label: p.name,
        description: p.name === current ? 'current' : '',
        detail: p.description,
        value: p.name,
      })),
    ];
    const picked = await vscode.window.showQuickPick(items, {
      title: 'Cobalto: which compiler runs the suites',
      placeHolder: 'cblt.json profile; saved in cobalto.profile for the workspace',
      matchOnDetail: true,
    });
    if (!picked) {
      return;
    }
    await vscode.workspace.getConfiguration('cobalto').update('profile', picked.value, vscode.ConfigurationTarget.Workspace);
    await this.refresh();
    const run = 'Run the suites';
    const answer = await vscode.window.showInformationMessage(`Cobalto: the suites run with the ${picked.value || defaultProfile} profile.`, run);
    if (answer === run) {
      await this.runAll();
    }
  }

  dispose(): void {
    this.status.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
