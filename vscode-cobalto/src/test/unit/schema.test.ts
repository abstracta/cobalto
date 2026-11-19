// Unit tests for src/dap/schema.ts: the schema version of the files in build/.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { schemaProblem, SUPPORTED_SCHEMA } from '../../dap/schema';

describe('schemaProblem', () => {
  test('a file with the supported schema has no problem', () => {
    assert.equal(schemaProblem({ schema: SUPPORTED_SCHEMA, cobalto: '0.7.0' }, 'build/TSTINV.layout.json'), undefined);
  });

  test('a file without the schema field (before 0.7.0) has no problem', () => {
    assert.equal(schemaProblem({}, 'build/TSTINV.layout.json'), undefined);
  });

  test('a file with an older schema has no problem', () => {
    assert.equal(schemaProblem({ schema: SUPPORTED_SCHEMA - 1 }, 'build/TSTINV.layout.json'), undefined);
  });

  test('a newer schema is a problem that names the file, the schema and the Cobalto that wrote it', () => {
    const problem = schemaProblem({ schema: SUPPORTED_SCHEMA + 1, cobalto: '9.1.0' }, 'build/TSTINV.layout.json');
    assert.ok(problem);
    assert.ok(problem.includes('build/TSTINV.layout.json'));
    assert.ok(problem.includes(`schema ${SUPPORTED_SCHEMA + 1}`));
    assert.ok(problem.includes('9.1.0'));
  });

  test('a newer schema is a problem even without the version of Cobalto', () => {
    assert.ok(schemaProblem({ schema: SUPPORTED_SCHEMA + 5 }, 'build/TSTINV.lines.json'));
  });
});
