// Lint rules of the extension: the recommended sets of ESLint and
// typescript-eslint, plus the few the code already follows.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['out/**', 'node_modules/**', '.vscode-test/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      curly: 'error',
      eqeqeq: 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
);
