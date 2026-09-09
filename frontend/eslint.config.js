import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'src/vendor/bklit'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-constant-binary-expression': 'error',
      'no-duplicate-imports': ['error', { allowSeparateTypeImports: true }],
      'no-implicit-coercion': 'error',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
)
