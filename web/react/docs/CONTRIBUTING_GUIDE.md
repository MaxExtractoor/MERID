# Contributing to MERID React Dashboard

## Overview

This guide covers how to contribute to the MERID React dashboard, including development setup, coding standards, and submission process.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)
- [Code Review Guidelines](#code-review-guidelines)

---

## Getting Started

### Prerequisites

- **Node.js**: 18.x or higher
- **npm**: 9.x or higher
- **Git**: Latest version
- **VS Code** (recommended) with extensions:
  - TypeScript and JavaScript Language Features
  - ESLint
  - Prettier
  - Auto Rename Tag
  - Path Intellisense

### Initial Setup

1. **Fork the repository**:
   - Click "Fork" on GitHub
   - Clone your fork locally

2. **Clone and setup**:
```bash
git clone <your-fork-url>
cd merid/web/react
npm install
```

3. **Create development branch**:
```bash
git checkout -b feature/your-feature-name
```

4. **Verify setup**:
```bash
npm run dev
npm run test
npm run type-check
```

### Environment Configuration

Create `.env.local` for development:
```env
VITE_API_BASE=http://localhost:8000
VITE_WS_URL=ws://localhost:3000
VITE_NODE_ENV=development
```

---

## Development Workflow

### Feature Development

1. **Create issue**: Create an issue describing the feature or bug
2. **Assign issue**: Assign to yourself or request assignment
3. **Create branch**: Use descriptive branch names:
   - `feature/trading-enhancement`
   - `fix/data-table-sorting`
   - `docs/api-reference`
   - `test/price-ticker-coverage`

### Daily Workflow

1. **Sync with main**:
```bash
git checkout main
git pull upstream main
git checkout your-branch
git rebase main
```

2. **Run tests**:
```bash
npm run test:watch
```

3. **Check types**:
```bash
npm run type-check
```

4. **Lint code**:
```bash
npm run lint
npm run lint:fix
```

### Commit Guidelines

#### Commit Message Format

Use conventional commits:

```
type(scope): description

[optional body]

[optional footer]
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Code formatting
- `refactor`: Code refactoring
- `test`: Test additions
- `chore`: Maintenance

**Examples**:
```
feat(trading): add stop-loss order support

Implement stop-loss orders with automatic execution
when price reaches specified threshold.

Closes #123
```

```
fix(data-table): resolve sorting pagination bug

Fixes issue where sorting was reset when changing pages
due to incorrect state management.

Fixes #456
```

### Branch Organization

- **main**: Production-ready code
- **develop**: Integration branch
- **feature/***: Feature branches
- **fix/***: Bug fix branches
- **release/***: Release branches

---

## Coding Standards

### TypeScript Standards

1. **Strict typing**: All functions and components must have proper types
2. **Interfaces**: Use interfaces for object shapes
3. **Generics**: Use generics for reusable components
4. **No `any`**: Avoid `any` type, use `unknown` instead

```typescript
// Good
interface MetricCardProps {
  label: string;
  value: string | number;
  status?: StatusType;
}

// Bad
interface MetricCardProps {
  label: any;
  value: any;
  status?: any;
}
```

### React Standards

1. **Functional components**: Use functional components with hooks
2. **Props destructuring**: Destructure props in function signature
3. **Default exports**: Use default exports for components
4. **PropTypes**: Use TypeScript instead of PropTypes

```typescript
// Good
interface Props {
  title: string;
  count?: number;
}

export default function Component({ title, count = 0 }: Props) {
  return <div>{title}: {count}</div>;
}

// Bad
export default function Component(props) {
  const { title, count = 0 } = props;
  return <div>{title}: {count}</div>;
}
```

### CSS and Styling

1. **Tailwind CSS**: Use Tailwind for all styling
2. **Component-scoped**: Avoid global styles
3. **Dark mode**: Support dark mode variants
4. **Responsive**: Use responsive prefixes

```typescript
// Good
<div className="bg-slate-900 border-slate-800 rounded-lg p-4 dark:bg-slate-800">
  <h2 className="text-lg font-semibold text-white">Title</h2>
</div>

// Bad
<div className="custom-component">
  <h2 className="title">Title</h2>
</div>
```

### File Organization

```
src/
├── components/          # Reusable components
│   ├── MetricCard.tsx
│   └── index.ts
├── hooks/               # Custom hooks
│   ├── useApiData.ts
│   └── index.ts
├── utils/               # Utility functions
│   ├── formatters.ts
│   └── index.ts
├── views/               # Page components
│   ├── Trading.tsx
│   └── index.ts
├── config/              # Configuration
│   └── constants.ts
├── types/               # TypeScript types
│   └── index.ts
└── __tests__/           # Test files
```

### Naming Conventions

1. **Components**: PascalCase (e.g., `MetricCard`)
2. **Files**: kebab-case (e.g., `metric-card.tsx`)
3. **Variables**: camelCase (e.g., `isLoading`)
4. **Constants**: UPPER_SNAKE_CASE (e.g., `API_ENDPOINTS`)
5. **Interfaces**: PascalCase with `I` prefix (e.g., `IMetricCardProps`)

### Code Quality

1. **Single responsibility**: Each function/component does one thing
2. **No magic numbers**: Use constants for magic values
3. **Error handling**: Handle errors gracefully
4. **Performance**: Optimize for performance

```typescript
// Good
const DEFAULT_PAGE_SIZE = 25;
const MAX_RETRIES = 3;

function fetchData(page = 1, retries = 0): Promise<Data> {
  try {
    const response = await fetch(`/api/data?page=${page}&size=${DEFAULT_PAGE_SIZE}`);
    if (!response.ok) throw new Error('Failed to fetch');
    return response.json();
  } catch (error) {
    if (retries < MAX_RETRIES) {
      return fetchData(page, retries + 1);
    }
    throw error;
  }
}

// Bad
function fetchData(page: number, retries: number): Promise<Data> {
  return fetch(`/api/data?page=${page}&size=25`)
    .then(response => response.json())
    .catch(error => {
      if (retries < 3) {
        return fetchData(page, retries + 1);
      }
      throw error;
    });
}
```

---

## Testing

### Testing Standards

1. **Coverage**: Maintain 80%+ test coverage
2. **Unit tests**: Test individual functions and components
3. **Integration tests**: Test component interactions
4. **E2E tests**: Test critical user flows

### Test Structure

```typescript
// Good test structure
describe('ComponentName', () => {
  beforeEach(() => {
    // Setup
  });

  it('should render correctly', () => {
    // Test basic rendering
  });

  it('should handle user interaction', () => {
    // Test interaction
  });

  it('should handle edge cases', () => {
    // Test edge cases
  });
});
```

### Component Testing

```typescript
// MetricCard.test.tsx
import { render, screen } from '@testing-library/react';
import { MetricCard } from '../MetricCard';

describe('MetricCard', () => {
  it('renders label and value', () => {
    render(<MetricCard label="Test" value="123" />);
    expect(screen.getByText('Test')).toBeInTheDocument();
    expect(screen.getByText('123')).toBeInTheDocument();
  });

  it('applies correct status styling', () => {
    const { container } = render(
      <MetricCard label="Test" value="123" status="GOOD" />
    );
    expect(container.firstChild).toHaveClass('border-green-500');
  });
});
```

### Hook Testing

```typescript
// useApiData.test.ts
import { renderHook, act } from '@testing-library/react';
import { useApiData } from '../useApiData';

describe('useApiData', () => {
  it('fetches data on mount', async () => {
    const mockData = { id: 1, name: 'Test' };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    const { result, waitForNextUpdate } = renderHook(() => 
      useApiData('/api/test')
    );

    expect(result.current.loading).toBe(true);

    await waitForNextUpdate();

    expect(result.current.data).toEqual(mockData);
    expect(result.current.loading).toBe(false);
  });
});
```

### Utility Testing

```typescript
// formatters.test.ts
import { formatCurrency } from '../formatters';

describe('formatCurrency', () => {
  it('formats USD correctly', () => {
    expect(formatCurrency(1234.56)).toBe('$1,234.56');
  });

  it('handles negative numbers', () => {
    expect(formatCurrency(-123.45)).toBe('-$123.45');
  });

  it('supports different currencies', () => {
    expect(formatCurrency(1234.56, 'EUR')).toBe('€1,234.56');
  });
});
```

### Running Tests

```bash
# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage

# Run specific test file
npm test -- MetricCard.test.tsx
```

---

## Documentation

### Documentation Standards

1. **JSDoc comments**: Document all public APIs
2. **README files**: Document each major component
3. **Examples**: Provide usage examples
4. **Type documentation**: Use TypeScript for self-documenting code

### JSDoc Examples

```typescript
/**
 * Formats a number as currency
 * @param amount - The amount to format
 * @param currency - Currency code (default: 'USD')
 * @param precision - Decimal places (default: 2)
 * @returns Formatted currency string
 * @example
 * formatCurrency(1234.56) // '$1,234.56'
 */
export function formatCurrency(
  amount: number,
  currency: string = 'USD',
  precision: number = 2
): string {
  // Implementation
}
```

### Component Documentation

Each component should have:

1. **Props interface**: Document all props
2. **Usage examples**: Show common usage patterns
3. **Accessibility notes**: Document accessibility features
4. **Performance notes**: Document performance considerations

```typescript
/**
 * MetricCard component for displaying KPI metrics
 * 
 * @example
 * <MetricCard
 *   label="Total P&L"
 *   value="$12,345.67"
 *   status="GOOD"
 *   delta={5.2}
 *   trend="up"
 * />
 */
export interface MetricCardProps {
  /** Metric label */
  label: string;
  /** Metric value */
  value: string | number;
  /** Status indicator */
  status?: StatusType;
  /** Delta value for change indicator */
  delta?: number;
  /** Trend direction */
  trend?: 'up' | 'down' | 'neutral';
}
```

---

## Pull Request Process

### Before Submitting

1. **Run all tests**: `npm test`
2. **Check types**: `npm run type-check`
3. **Lint code**: `npm run lint`
4. **Build successfully**: `npm run build`
5. **Update documentation**: If needed

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added
- [ ] Manual testing completed

## Checklist
- [ ] Code follows project standards
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Build passes successfully

## Screenshots
Add screenshots for UI changes

## Related Issues
Closes #123
```

### Review Process

1. **Self-review**: Review your own code first
2. **Request review**: Request review from team members
3. **Address feedback**: Make requested changes
4. **Approval**: Get approval before merge

### Merge Requirements

- At least one approval from team member
- All CI checks passing
- No merge conflicts
- Documentation updated if needed

---

## Code Review Guidelines

### Review Checklist

#### Functionality
- [ ] Code works as intended
- [ ] Edge cases handled
- [ ] Error handling appropriate
- [ ] Performance considered

#### Code Quality
- [ ] Code is readable and maintainable
- [ ] Follows project standards
- [ ] No duplicate code
- [ ] Proper error handling

#### Testing
- [ ] Tests cover main functionality
- [ ] Tests cover edge cases
- [ ] Tests are maintainable
- [ ] No test anti-patterns

#### Documentation
- [ ] Code is self-documenting
- [ ] JSDoc comments added
- [ ] README updated if needed
- [ ] Examples provided

### Review Best Practices

1. **Be constructive**: Provide helpful, specific feedback
2. **Explain reasoning**: Explain why changes are needed
3. **Suggest improvements**: Offer concrete suggestions
4. **Acknowledge good work**: Recognize well-written code

### Review Comments Format

```markdown
**Suggestion**: Consider using a more descriptive variable name

**Issue**: This could cause a memory leak if not cleaned up

**Question**: Have you considered the edge case where the API returns null?

**Praise**: Great use of TypeScript generics here!
```

---

## Development Tools

### Recommended VS Code Extensions

1. **TypeScript and JavaScript Language Features**
2. **ESLint**
3. **Prettier**
4. **Auto Rename Tag**
5. **Path Intellisense**
6. **GitLens**
7. **Thunder Client** (for API testing)
8. **Jest Runner**

### VS Code Settings

Create `.vscode/settings.json`:

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  },
  "typescript.preferences.importModuleSpecifier": "relative",
  "emmet.includeLanguages": ["typescript", "typescriptreact"],
  "files.exclude": {
    "**/node_modules": true,
    "**/dist": true
  }
}
```

### ESLint Configuration

The project uses ESLint with TypeScript and React rules. Configuration in `.eslintrc.js`:

```javascript
module.exports = {
  extends: [
    'eslint:recommended',
    '@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  rules: {
    // Custom rules
  },
};
```

### Prettier Configuration

Configuration in `.prettierrc`:

```json
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 80,
  "tabWidth": 2,
  "useTabs": false
}
```

---

## Getting Help

### Resources

1. **Documentation**: Check existing docs first
2. **Code examples**: Look at similar components
3. **Team members**: Ask for guidance
4. **GitHub issues**: Search for similar issues

### Communication Channels

1. **GitHub Discussions**: General questions
2. **GitHub Issues**: Bug reports and feature requests
3. **Slack**: Real-time discussions
4. **Email**: Private matters

### First-Time Contributors

Welcome! We're glad you're here. Here's how to get started:

1. **Start small**: Pick a good first issue
2. **Ask questions**: We're here to help
3. **Learn**: Review existing code patterns
4. **Contribute**: Every contribution matters

### Recognition

Contributors are recognized in:
- `CONTRIBUTORS.md` file
- Release notes
- Team meetings
- Annual reviews

---

## Release Process

### Version Management

We use semantic versioning:
- **Major**: Breaking changes (2.x.x)
- **Minor**: New features (1.x.x)
- **Patch**: Bug fixes (1.1.x)

### Release Checklist

1. **Update version**: Update package.json
2. **Update CHANGELOG**: Document changes
3. **Tag release**: Create git tag
4. **Build artifacts**: Create production build
5. **Deploy**: Deploy to production
6. **Announce**: Notify users

---

## Community Guidelines

### Code of Conduct

1. **Be respectful**: Treat everyone with respect
2. **Be inclusive**: Welcome all contributors
3. **Be constructive**: Provide helpful feedback
4. **Be patient**: Help others learn

### Conflict Resolution

1. **Discuss issues**: Talk through disagreements
2. **Seek mediation**: Ask maintainers for help
3. **Focus on solutions**: Work toward resolution
4. **Move forward**: Don't dwell on conflicts

---

## Questions?

If you have questions about contributing:

1. **Check documentation**: Review this guide first
2. **Search issues**: Look for similar questions
3. **Ask in discussions**: Post general questions
4. **Contact maintainers**: Reach out directly

Thank you for contributing to MERID! 🚀
