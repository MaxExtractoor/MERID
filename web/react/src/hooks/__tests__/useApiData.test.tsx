import { render, screen, waitFor } from '@testing-library/react';
import { useApiData } from '../useApiData';

// Mock fetch
global.fetch = jest.fn();

interface TestOptions {
  pollingInterval?: number;
  initialData?: unknown;
  enabled?: boolean;
  transform?: (data: unknown) => unknown;
}

// Test component wrapper
function TestComponent({ endpoint, options }: { endpoint: string; options?: TestOptions }) {
  const result = useApiData(endpoint, options);
  return (
    <div>
      <div data-testid="loading">{result.loading ? 'loading' : 'loaded'}</div>
      <div data-testid="data">{JSON.stringify(result.data)}</div>
      <div data-testid="error">{result.error?.message || 'no error'}</div>
    </div>
  );
}

describe('useApiData', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('initializes with default state', () => {
    render(<TestComponent endpoint="/api/test" />);
    
    expect(screen.getByTestId('loading')).toHaveTextContent('loading');
    expect(screen.getByTestId('data')).toHaveTextContent('null');
    expect(screen.getByTestId('error')).toHaveTextContent('no error');
  });

  it('fetches data successfully', async () => {
    const mockData = { id: 1, name: 'Test Data' };
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    render(<TestComponent endpoint="/api/test" />);

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });
    await waitFor(() => {
      expect(screen.getByTestId('data')).toHaveTextContent(JSON.stringify(mockData));
    });
    expect(screen.getByTestId('error')).toHaveTextContent('no error');
  });

  it('handles fetch error', async () => {
    const mockError = new Error('Network error');
    (fetch as jest.Mock).mockRejectedValueOnce(mockError);

    render(<TestComponent endpoint="/api/test" />);

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });
    await waitFor(() => {
      expect(screen.getByTestId('data')).toHaveTextContent('null');
    });
    expect(screen.getByTestId('error')).toHaveTextContent('Network error');
  });

  it('handles polling', async () => {
    const mockData = { id: 1, name: 'Test Data' };
    (fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    render(<TestComponent endpoint="/api/test" options={{ pollingInterval: 1000 }} />);

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });
    await waitFor(() => {
      expect(screen.getByTestId('data')).toHaveTextContent(JSON.stringify(mockData));
    });
  });

  it('handles data transformation', async () => {
    const mockData = { value: 5 };
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    render(<TestComponent 
      endpoint="/api/test" 
      options={{
        transform: (data: unknown) => {
          const value = typeof data === 'object' && data !== null && 'value' in data
            ? (data as { value?: number }).value
            : undefined;
          return { doubled: typeof value === 'number' ? value * 2 : 0 };
        }
      }} 
    />);

    await waitFor(() => {
      expect(screen.getByTestId('data')).toHaveTextContent(JSON.stringify({ doubled: 10 }));
    });
  });

  it('handles enabled/disabled', () => {
    render(<TestComponent endpoint="/api/test" options={{ enabled: false }} />);
    
    expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    expect(screen.getByTestId('data')).toHaveTextContent('null');
    expect(screen.getByTestId('error')).toHaveTextContent('no error');
  });

  it('handles initial data', () => {
    const initialData = { id: 1, name: 'Initial' };
    
    render(<TestComponent endpoint="/api/test" options={{ initialData }} />);
    
    expect(screen.getByTestId('data')).toHaveTextContent(JSON.stringify(initialData));
  });
});
