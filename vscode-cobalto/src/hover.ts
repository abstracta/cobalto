// Evaluatable expression under the cursor: without a provider of its own, VS Code
// cuts the word with a C-like identifier rule, so a COBOL name such as
// WS-C-AMOUNT becomes "C" or "AMOUNT" and the debug hover shows nothing.

import * as vscode from 'vscode';

/** Languages in which COBOL names are evaluated: the DSL itself and the ids
 *  that the usual COBOL extensions use for .cbl files. */
export const COBOL_LANGUAGES = ['cobalto-test', 'COBOL', 'cobol', 'BITLANG-COBOL', 'ACUCOBOL', 'COBOLIT'];

const WORD_RE = /[A-Za-z0-9][A-Za-z0-9-]*/g;

/** Range of the COBOL name (letters, digits and hyphens) that contains the position. */
export function cobolWordRangeAt(document: vscode.TextDocument, position: vscode.Position): vscode.Range | undefined {
  const text = document.lineAt(position.line).text;
  WORD_RE.lastIndex = 0;
  for (let m = WORD_RE.exec(text); m; m = WORD_RE.exec(text)) {
    const start = m.index;
    const end = start + m[0].length;
    if (position.character >= start && position.character <= end) {
      return new vscode.Range(position.line, start, position.line, end);
    }
    if (start > position.character) {
      break;
    }
  }
  return undefined;
}

export function expressionAt(document: vscode.TextDocument, position: vscode.Position): string | undefined {
  const range = cobolWordRangeAt(document, position);
  return range ? document.getText(range) : undefined;
}

class CobolEvaluatableExpressionProvider implements vscode.EvaluatableExpressionProvider {
  provideEvaluatableExpression(document: vscode.TextDocument, position: vscode.Position): vscode.EvaluatableExpression | undefined {
    const range = cobolWordRangeAt(document, position);
    if (!range) {
      return undefined;
    }
    const word = document.getText(range);
    // COBOL names: at least one letter; numbers and literals are not evaluated
    return /[A-Za-z]/.test(word) ? new vscode.EvaluatableExpression(range, word) : undefined;
  }
}

export function registerEvaluatableExpressionProviders(): vscode.Disposable {
  const selector: vscode.DocumentSelector = COBOL_LANGUAGES.map((language) => ({ language, scheme: 'file' }));
  return vscode.languages.registerEvaluatableExpressionProvider(selector, new CobolEvaluatableExpressionProvider());
}
