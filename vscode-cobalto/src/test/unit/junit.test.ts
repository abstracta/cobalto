// Unit tests for src/junit.ts: the reader of build/junit.xml. The fixtures
// follow the structure the CLI writes (one tag per line, CDATA for texts).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { JunitCase, parseJunit } from '../../junit';

function document(...suites: string[]): string {
  return ['<?xml version="1.0" encoding="UTF-8"?>', '<testsuites>', ...suites, '</testsuites>', ''].join('\n');
}

function suite(name: string, counters: string, ...cases: string[]): string {
  return [`  <testsuite name="${name}" ${counters}>`, ...cases, '  </testsuite>'].join('\n');
}

function testCase(name: string, ...children: string[]): string {
  return [`    <testcase name="${name}" classname="TSTINV">`, ...children.map((c) => `      ${c}`), '    </testcase>'].join('\n');
}

function properties(values: Record<string, string>): string {
  const list = Object.entries(values).map(([n, v]) => `<property name="${n}" value="${v}"/>`);
  return `<properties>${list.join('')}</properties>`;
}

const ONE_CASE = 'tests="1" failures="0" errors="0" skipped="0"';
const INTERNAL = properties({ 'cobalto.kind': 'internal' });

/** The only test case of a document with one suite. */
function onlyCase(...children: string[]): JunitCase {
  const suites = parseJunit(document(suite('TSTINV', ONE_CASE, testCase('one line is calculated', ...children))));
  assert.equal(suites.length, 1);
  assert.equal(suites[0].cases.length, 1);
  return suites[0].cases[0];
}

describe('parseJunit: suites', () => {
  test('reads the name and the counters of a suite from its attributes', () => {
    const [s] = parseJunit(document(suite('TSTBATCH', 'tests="13" failures="2" errors="1" skipped="3"')));
    assert.deepEqual({ name: s.name, tests: s.tests, failures: s.failures, errors: s.errors, skipped: s.skipped }, { name: 'TSTBATCH', tests: 13, failures: 2, errors: 1, skipped: 3 });
  });

  test('counters that are missing count as zero', () => {
    const [s] = parseJunit(document(suite('TSTINV', 'tests="1"', testCase('a case'))));
    assert.deepEqual([s.failures, s.errors, s.skipped], [0, 0, 0]);
  });

  test('a suite without test cases has an empty list of cases', () => {
    const [s] = parseJunit(document(suite('TSTINV', 'tests="0" failures="0" errors="0" skipped="0"')));
    assert.deepEqual(s.cases, []);
  });

  test('several suites come in document order, each with its own cases', () => {
    const suites = parseJunit(document(
      suite('TSTINV', 'tests="2" failures="0" errors="0" skipped="0"', testCase('first of INV', INTERNAL), testCase('second of INV', INTERNAL)),
      suite('TSTDISC', ONE_CASE, testCase('first of DISC', INTERNAL)),
      suite('TSTLOAN', ONE_CASE, testCase('first of LOAN', INTERNAL)),
    ));
    assert.deepEqual(suites.map((s) => [s.name, s.cases.map((c) => c.name)]), [
      ['TSTINV', ['first of INV', 'second of INV']],
      ['TSTDISC', ['first of DISC']],
      ['TSTLOAN', ['first of LOAN']],
    ]);
  });

  test('each case records the suite it belongs to', () => {
    const suites = parseJunit(document(suite('TSTINV', ONE_CASE, testCase('a')), suite('TSTDISC', ONE_CASE, testCase('b'))));
    assert.deepEqual(suites.flatMap((s) => s.cases.map((c) => c.suite)), ['TSTINV', 'TSTDISC']);
  });

  test('a document without suites yields an empty list', () => {
    assert.deepEqual(parseJunit(document()), []);
    assert.deepEqual(parseJunit(''), []);
  });
});

describe('parseJunit: outcome of a test case', () => {
  test('a case without failure, error or skipped is a passed case', () => {
    const c = onlyCase(INTERNAL);
    assert.equal(c.name, 'one line is calculated');
    assert.equal(c.skipped, false);
    assert.equal(c.failure, undefined);
    assert.equal(c.error, undefined);
    assert.equal(c.output, undefined);
  });

  test('a failed case carries the message and the text of the failure', () => {
    const c = onlyCase(
      properties({ 'cobalto.kind': 'interface', 'cobalto.expected': '700.000', 'cobalto.actual': '630.000' }),
      '<failure message="#11 EQNUM: expected [700.000] actual [630.000]"><![CDATA[#11 EQNUM: expected [700.000] actual [630.000]\n#12 EQ: expected [PREMIUM] actual [STANDARD]]]></failure>',
    );
    assert.equal(c.failure?.message, '#11 EQNUM: expected [700.000] actual [630.000]');
    assert.equal(c.failure?.text, '#11 EQNUM: expected [700.000] actual [630.000]\n#12 EQ: expected [PREMIUM] actual [STANDARD]');
    assert.equal(c.skipped, false);
    assert.equal(c.error, undefined);
  });

  test('a failed case carries the expected and actual values of its properties', () => {
    const c = onlyCase(
      properties({ 'cobalto.kind': 'interface', 'cobalto.expected': '700.000', 'cobalto.actual': '630.000' }),
      '<failure message="#11 EQNUM"><![CDATA[#11 EQNUM]]></failure>',
    );
    assert.equal(c.failure?.expected, '700.000');
    assert.equal(c.failure?.actual, '630.000');
  });

  test('a failure without the expected and actual properties leaves them undefined', () => {
    const c = onlyCase(INTERNAL, '<failure message="#3 CALLED: DISCOUNT was not called"><![CDATA[#3 CALLED: DISCOUNT was not called]]></failure>');
    assert.ok(c.failure);
    assert.equal(c.failure.expected, undefined);
    assert.equal(c.failure.actual, undefined);
  });

  test('a failure with an empty body uses the message as its text', () => {
    const c = onlyCase(INTERNAL, '<failure message="#4 EQ: expected [A] actual [B]"></failure>');
    assert.equal(c.failure?.text, '#4 EQ: expected [A] actual [B]');
  });

  test('an aborted case carries the message of the error', () => {
    const c = onlyCase(INTERNAL, '<error message="The test aborted before finishing"/>');
    assert.equal(c.error, 'The test aborted before finishing');
    assert.equal(c.failure, undefined);
  });

  test('an error without a message still marks the case as errored', () => {
    const c = onlyCase(INTERNAL, '<error/>');
    assert.ok(c.error);
  });

  test('a skipped case is marked as skipped', () => {
    const c = onlyCase(INTERNAL, '<skipped/>');
    assert.equal(c.skipped, true);
    assert.equal(c.failure, undefined);
    assert.equal(c.error, undefined);
  });

  test('the outcome of one case does not leak into its neighbours', () => {
    const [s] = parseJunit(document(suite(
      'TSTINV',
      'tests="4" failures="1" errors="1" skipped="1"',
      testCase('passes before', INTERNAL),
      testCase('fails', properties({ 'cobalto.kind': 'internal', 'cobalto.expected': '2', 'cobalto.actual': '3' }), '<failure message="#1 EQNUM"><![CDATA[#1 EQNUM]]></failure>', '<system-out><![CDATA[trace of the failed case]]></system-out>'),
      testCase('is skipped', INTERNAL, '<skipped/>'),
      testCase('aborts', INTERNAL, '<error message="The test aborted before finishing"/>'),
    )));
    const [before, failed, skipped, aborted] = s.cases;
    assert.deepEqual(before, { suite: 'TSTINV', name: 'passes before', skipped: false, kind: 'internal' });
    assert.ok(failed.failure);
    assert.equal(failed.skipped, false);
    assert.equal(failed.error, undefined);
    assert.deepEqual(skipped, { suite: 'TSTINV', name: 'is skipped', skipped: true, kind: 'internal' });
    assert.deepEqual(aborted, { suite: 'TSTINV', name: 'aborts', skipped: false, kind: 'internal', error: 'The test aborted before finishing' });
  });

  test('cases with the same name are all kept, in order', () => {
    const [s] = parseJunit(document(suite(
      'TSTINV',
      'tests="3" failures="1" errors="0" skipped="1"',
      testCase('repeated name', INTERNAL),
      testCase('repeated name', INTERNAL, '<failure message="#2 EQ"><![CDATA[#2 EQ]]></failure>'),
      testCase('repeated name', INTERNAL, '<skipped/>'),
    )));
    assert.deepEqual(s.cases.map((c) => c.name), ['repeated name', 'repeated name', 'repeated name']);
    assert.deepEqual(s.cases.map((c) => (c.skipped ? 'skipped' : c.failure ? 'failed' : 'passed')), ['passed', 'failed', 'skipped']);
  });
});

describe('parseJunit: kind and output', () => {
  test('the kind property tells an interface case from an internal one', () => {
    assert.equal(onlyCase(properties({ 'cobalto.kind': 'interface' })).kind, 'interface');
    assert.equal(onlyCase(properties({ 'cobalto.kind': 'internal' })).kind, 'internal');
  });

  test('a case the CLI did not classify has no kind', () => {
    const c = onlyCase();
    assert.equal(c.kind, undefined);
    assert.equal(c.skipped, false);
  });

  test('the output of a case comes from system-out', () => {
    const c = onlyCase(INTERNAL, '<system-out><![CDATA[premium result: 0001600.00]]></system-out>');
    assert.equal(c.output, 'premium result: 0001600.00');
  });

  test('output of several lines keeps its line breaks', () => {
    const c = onlyCase(INTERNAL, '<system-out><![CDATA[first line\nsecond line\n  third, indented]]></system-out>');
    assert.equal(c.output, 'first line\nsecond line\n  third, indented');
  });

  test('a failed case can also carry output', () => {
    const c = onlyCase(INTERNAL, '<failure message="#1 EQ"><![CDATA[#1 EQ: expected [A] actual [B]]]></failure>', '<system-out><![CDATA[before the assert]]></system-out>');
    assert.equal(c.failure?.text, '#1 EQ: expected [A] actual [B]');
    assert.equal(c.output, 'before the assert');
  });

  test('text that looks like markup inside the output is not read as tags', () => {
    const c = onlyCase(INTERNAL, '<system-out><![CDATA[<error code="5">bad</error> <skipped/> </testcase>]]></system-out>');
    assert.equal(c.skipped, false);
    assert.equal(c.error, undefined);
    assert.equal(c.failure, undefined);
    assert.equal(c.output, '<error code="5">bad</error> <skipped/> </testcase>');
  });
});

describe('parseJunit: XML entities', () => {
  test('entities in the name of a case are decoded', () => {
    const [s] = parseJunit(document(suite('TSTINV', ONE_CASE, testCase('net &lt; 1000 &amp; category &quot;BASIC&quot; isn&apos;t &gt; standard', INTERNAL))));
    assert.equal(s.cases[0].name, 'net < 1000 & category "BASIC" isn\'t > standard');
  });

  test('entities in the name of a suite are decoded', () => {
    const [s] = parseJunit(document(suite('A&amp;B', ONE_CASE, testCase('a case'))));
    assert.equal(s.name, 'A&B');
    assert.equal(s.cases[0].suite, 'A&B');
  });

  test('entities in expected, actual and the failure message are decoded', () => {
    const c = onlyCase(
      properties({ 'cobalto.kind': 'internal', 'cobalto.expected': '&lt;A&gt; &amp; &quot;B&quot;', 'cobalto.actual': '&lt;C&gt;' }),
      '<failure message="#1 EQ: expected [&lt;A&gt; &amp; &quot;B&quot;] actual [&lt;C&gt;]"><![CDATA[#1 EQ]]></failure>',
    );
    assert.equal(c.failure?.expected, '<A> & "B"');
    assert.equal(c.failure?.actual, '<C>');
    assert.equal(c.failure?.message, '#1 EQ: expected [<A> & "B"] actual [<C>]');
  });

  test('an escaped ampersand is decoded only once', () => {
    const [s] = parseJunit(document(suite('TSTINV', ONE_CASE, testCase('writes &amp;lt; as text'))));
    assert.equal(s.cases[0].name, 'writes &lt; as text');
  });

  test('text inside CDATA is taken verbatim', () => {
    const c = onlyCase(INTERNAL, '<failure message="#1 EQ"><![CDATA[#1 EQ: expected [A & B] actual [&amp;]]]></failure>', '<system-out><![CDATA[1 < 2 &lt; 3]]></system-out>');
    assert.equal(c.failure?.text, '#1 EQ: expected [A & B] actual [&amp;]');
    assert.equal(c.output, '1 < 2 &lt; 3');
  });

  test('text outside CDATA has its entities decoded', () => {
    const c = onlyCase(INTERNAL, '<system-out>1 &lt; 2 &amp; 3 &gt; 2</system-out>');
    assert.equal(c.output, '1 < 2 & 3 > 2');
  });
});
