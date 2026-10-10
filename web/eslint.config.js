// Flat config: recommended JS + type-aware TypeScript rules for src/, node globals for configs.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts"],
    languageOptions: { globals: globals.browser },
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      eqeqeq: ["error", "smart"],
      "no-console": "error",
    },
  },
  { files: ["*.config.{js,ts}", "scripts/**/*.mjs", "src/**/*.test.ts"], languageOptions: { globals: globals.node } },
);
