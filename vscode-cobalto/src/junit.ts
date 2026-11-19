// Minimal reader for the build/junit.xml that cblt writes (the CLI itself
// generates it, with a fixed structure: testsuite > testcase > properties|skipped|failure|error|system-out).
// What the JUnit format lacks travels in test case properties: cobalto.kind
// (interface or internal) and, on failure, cobalto.expected and cobalto.actual of
// the first assert that failed. The <failure> text is for people: it is not parsed.

export interface JunitCase {
  suite: string;
  name: string;
  skipped: boolean;
  /** "interface" | "internal"; empty if the CLI did not classify the test case */
  kind?: string;
  failure?: { message: string; text: string; expected?: string; actual?: string };
  error?: string;
  output?: string;
}

export interface JunitSuite {
  name: string;
  tests: number;
  failures: number;
  errors: number;
  skipped: number;
  cases: JunitCase[];
}

function unescape(s: string): string {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');
}

function attr(tag: string, name: string): string {
  const m = new RegExp(`\\b${name}="([^"]*)"`).exec(tag);
  return m ? unescape(m[1]) : '';
}

function properties(block: string): Map<string, string> {
  const props = new Map<string, string>();
  for (const m of block.matchAll(/<property\b([^>]*)\/>/g)) {
    props.set(attr(m[1], 'name'), attr(m[1], 'value'));
  }
  return props;
}

/** Text of an element: its CDATA section (kept apart in texts, see
 *  parseJunit) or its escaped content. */
function cdata(block: string, tag: string, texts: string[]): string | undefined {
  const m = new RegExp(`<${tag}\\b[^>]*>(?:<!\\[CDATA\\[(\\d+)\\]\\]>)?([\\s\\S]*?)</${tag}>`).exec(block);
  if (!m) {
    return undefined;
  }
  return m[1] !== undefined ? texts[parseInt(m[1], 10)] : unescape(m[2]);
}

export function parseJunit(xml: string): JunitSuite[] {
  const suites: JunitSuite[] = [];
  // The CDATA sections hold what the program wrote, which may look like
  // markup (even like "</testcase>"). They are set aside before reading the
  // tags, each one replaced by its number.
  const texts: string[] = [];
  const tags = xml.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, (_all, text: string) => `<![CDATA[${texts.push(text) - 1}]]>`);
  const suiteRe = /<testsuite\b([^>]*)>([\s\S]*?)<\/testsuite>/g;
  for (const sm of tags.matchAll(suiteRe)) {
    const suite: JunitSuite = {
      name: attr(sm[1], 'name'),
      tests: parseInt(attr(sm[1], 'tests') || '0', 10),
      failures: parseInt(attr(sm[1], 'failures') || '0', 10),
      errors: parseInt(attr(sm[1], 'errors') || '0', 10),
      skipped: parseInt(attr(sm[1], 'skipped') || '0', 10),
      cases: [],
    };
    const caseRe = /<testcase\b([^>]*)>([\s\S]*?)<\/testcase>/g;
    for (const cm of sm[2].matchAll(caseRe)) {
      const body = cm[2];
      const props = properties(body);
      const c: JunitCase = { suite: suite.name, name: attr(cm[1], 'name'), skipped: /<skipped\s*\/>/.test(body) };
      if (props.has('cobalto.kind')) {
        c.kind = props.get('cobalto.kind');
      }
      const failTag = /<failure\b([^>]*)>/.exec(body);
      if (failTag) {
        const text = cdata(body, 'failure', texts) ?? '';
        const message = attr(failTag[1], 'message');
        c.failure = {
          message,
          text: text || message,
          expected: props.get('cobalto.expected'),
          actual: props.get('cobalto.actual'),
        };
      }
      const errTag = /<error\b([^>]*)\/?>/.exec(body);
      if (errTag) {
        c.error = attr(errTag[1], 'message') || 'error';
      }
      const out = cdata(body, 'system-out', texts);
      if (out) {
        c.output = out;
      }
      suite.cases.push(c);
    }
    suites.push(suite);
  }
  return suites;
}
