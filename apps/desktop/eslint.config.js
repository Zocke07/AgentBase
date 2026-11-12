import js from "@eslint/js";
import { createNodeResolver, flatConfigs as importX } from "eslint-plugin-import-x";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefreshPlugin from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * BUILD_SPEC §5 Phase 0.
 *
 * `import-x/no-unresolved` with `caseSensitiveStrict` catches locally the path
 * case mismatches that resolve on Windows/macOS but fail on Linux CI.
 */
export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "src-tauri/**", "coverage/**"],
  },

  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  importX.recommended,
  importX.typescript,

  {
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      "import-x/resolver-next": [
        createNodeResolver({
          extensions: [".ts", ".tsx", ".js", ".jsx", ".json"],
        }),
      ],
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefreshPlugin,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // Phase 0 requires case-sensitive import paths.
      "import-x/no-unresolved": [
        "error",
        { caseSensitive: true, caseSensitiveStrict: true },
      ],
      "import-x/no-useless-path-segments": ["error", { noUselessIndex: true }],
      "import-x/no-absolute-path": "error",
      "import-x/no-self-import": "error",
      "import-x/no-cycle": ["error", { maxDepth: 8 }],
      "import-x/order": [
        "error",
        {
          groups: [
            "builtin",
            "external",
            "internal",
            "parent",
            "sibling",
            "index",
          ],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: false },
        },
      ],

      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      // Use the event log, not the browser console, as the output channel.
      "no-console": ["warn", { allow: ["warn", "error"] }],
      eqeqeq: ["error", "always"],
    },
  },

  // Config files and development scripts run in Node.
  {
    files: ["vite.config.ts", "vitest.browser.config.ts", "eslint.config.js", "scripts/**/*.ts"],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["eslint.config.js"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
