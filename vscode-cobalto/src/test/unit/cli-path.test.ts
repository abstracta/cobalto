// Unit tests for src/cli-path.ts: where the cobalto executable is. Each test
// builds its own project folder under a temporary directory. The platform is
// always given, so that the result does not depend on the host.

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { resolveCli } from '../../cli-path';

describe('resolveCli', () => {
  let tmp = '';
  let count = 0;

  before(() => {
    tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cobalto-cli-path-')));
  });

  after(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  /** A new, empty folder: nothing in it or above it (up to tmp) holds a .venv. */
  function workspace(): string {
    const dir = path.join(tmp, `workspace-${++count}`);
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  function touch(...parts: string[]): string {
    const file = path.join(...parts);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, '');
    return file;
  }

  test('a relative path from the settings starts at the project folder', () => {
    const project = workspace();
    assert.equal(resolveCli(project, path.join('tools', 'cobalto'), 'linux'), path.join(project, 'tools', 'cobalto'));
  });

  test('an absolute path from the settings is used as it is', () => {
    const project = workspace();
    const custom = path.join(tmp, 'elsewhere', 'bin', 'cobalto');
    assert.equal(resolveCli(project, custom, 'linux'), custom);
  });

  test('the path from the settings wins over a virtual environment', () => {
    const project = workspace();
    touch(project, '.venv', 'bin', 'cobalto');
    assert.equal(resolveCli(project, path.join('tools', 'cobalto'), 'linux'), path.join(project, 'tools', 'cobalto'));
  });

  test('without a setting, the virtual environment of the project folder is used', () => {
    const project = workspace();
    const inVenv = touch(project, '.venv', 'bin', 'cobalto');
    assert.equal(resolveCli(project, '', 'linux'), inVenv);
  });

  test('a virtual environment in a folder above the project is found', () => {
    const repo = workspace();
    const inVenv = touch(repo, '.venv', 'bin', 'cobalto');
    const project = path.join(repo, 'apps', 'billing');
    fs.mkdirSync(project, { recursive: true });
    assert.equal(resolveCli(project, '', 'linux'), inVenv);
  });

  test('the nearest virtual environment wins', () => {
    const repo = workspace();
    touch(repo, '.venv', 'bin', 'cobalto');
    const project = path.join(repo, 'apps', 'billing');
    const nearest = touch(project, '.venv', 'bin', 'cobalto');
    assert.equal(resolveCli(project, '', 'linux'), nearest);
  });

  test('on Windows the executable of the virtual environment is Scripts/cobalto.exe', () => {
    const project = workspace();
    touch(project, '.venv', 'bin', 'cobalto');
    const exe = touch(project, '.venv', 'Scripts', 'cobalto.exe');
    assert.equal(resolveCli(project, '', 'win32'), exe);
  });

  test('a virtual environment without cobalto installed is not used', () => {
    const project = workspace();
    touch(project, '.venv', 'bin', 'python');
    assert.equal(resolveCli(project, '', 'linux'), 'cobalto');
  });

  test('without a setting or a virtual environment the command is left to the PATH', () => {
    const project = workspace();
    assert.equal(resolveCli(project, '', 'linux'), 'cobalto');
  });
});
