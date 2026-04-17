module.exports = {
  rules: {
    // ── Audit regression guards (UI-001 through UI-010) ──────────────
    'no-window-reload': {
      meta: {
        type: 'problem',
        docs: {
          description: 'Prevent window.location.reload() outside error boundaries — use targeted refetch instead (UI-004)',
          category: 'Best Practices',
          recommended: true,
        },
        fixable: null,
        schema: [],
        messages: {
          noReload: 'Avoid window.location.reload(). Use targeted refetch/fetch calls instead. See UI-004 in the audit.',
        },
      },
      create(context) {
        return {
          CallExpression(node) {
            const callee = node.callee;
            if (
              callee.type === 'MemberExpression' &&
              callee.object?.type === 'MemberExpression' &&
              callee.object.object?.name === 'window' &&
              callee.object.property?.name === 'location' &&
              callee.property?.name === 'reload'
            ) {
              const filename = context.getFilename();
              // Allow in error boundaries and feature flag files
              if (
                !filename.includes('ErrorBoundary') &&
                !filename.includes('featureFlags')
              ) {
                context.report({ node, messageId: 'noReload' });
              }
            }
          },
        };
      },
    },

    'no-unstable-hook-deps': {
      meta: {
        type: 'problem',
        docs: {
          description: 'Prevent full useApiData result objects in useEffect/useCallback dependency arrays (UI-002/UI-009)',
          category: 'Best Practices',
          recommended: true,
        },
        fixable: null,
        schema: [],
        messages: {
          unstableDep: 'Dependency "{{name}}" looks like a full hook result object (ends with Result). Extract .refetch or .data before using in deps. See UI-002/UI-009.',
        },
      },
      create(context) {
        return {
          CallExpression(node) {
            const callee = node.callee;
            if (
              callee.type === 'Identifier' &&
              (callee.name === 'useEffect' || callee.name === 'useCallback' || callee.name === 'useMemo')
            ) {
              const depsArg = node.arguments[1];
              if (depsArg && depsArg.type === 'ArrayExpression') {
                for (const el of depsArg.elements) {
                  if (el && el.type === 'Identifier' && /Result$/.test(el.name)) {
                    context.report({
                      node: el,
                      messageId: 'unstableDep',
                      data: { name: el.name },
                    });
                  }
                }
              }
            }
          },
        };
      },
    },

    // ── Existing rules ───────────────────────────────────────────────
    'no-direct-lucide-imports': {
      meta: {
        type: 'problem',
        docs: {
          description: 'Prevent direct imports from lucide-react outside icons.ts',
          category: 'Best Practices',
          recommended: true,
        },
        fixable: null,
        schema: [],
        messages: {
          noDirectImport: 'Direct import from lucide-react is not allowed. Import from ../ui/icons instead.',
        },
      },
      create(context) {
        return {
          ImportDeclaration(node) {
            const source = node.source.value;
            
            // Check if this is a direct lucide-react import
            if (source === 'lucide-react' || source.startsWith('lucide-react/')) {
              // Get the current file path
              const filename = context.getFilename();
              
              // Allow imports in icons.ts and test files
              if (!filename.includes('icons.ts') && 
                  !filename.includes('.test.') && 
                  !filename.includes('__tests__')) {
                context.report({
                  node,
                  messageId: 'noDirectImport',
                });
              }
            }
          },
        };
      },
    },
  },
};
