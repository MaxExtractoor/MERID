/**
 * Tests for PublishPipelinePanel — pipeline status, recent posts, manual trigger.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

jest.mock('../../config/constants', () => ({
  API_ENDPOINTS: {
    KALSHI_PUBLISH_PIPELINE: '/api/v1/kalshi/publish-pipeline',
    KALSHI_PUBLISH_PIPELINE_TRIGGER: '/api/v1/kalshi/publish-pipeline/trigger',
  },
  DEFAULTS: { POLLING_INTERVALS: { STANDARD: 30000 } },
}));

import PublishPipelinePanel from '../PublishPipelinePanel';

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_PIPELINE_RUNNING = {
  pipeline: {
    running: true,
    consumers: 1,
    tracked_tickers: 42,
    total_emitted: 18,
    by_category: { Trending: 8, Politics: 5, Crypto: 5 },
    by_action: { swing: 10, prob_cross: 8 },
    errors: 0,
    started_at: '2026-02-19T00:00:00Z',
  },
  news_agent: {
    total_processed: 18,
    total_telegram: 15,
    total_x: 12,
    skipped_cooldown: 3,
    errors: 0,
    recent_posts: [
      {
        ticker: 'KXBTC-1H-T95000',
        category: 'Crypto',
        action: 'swing',
        telegram: true,
        tweet_id: '1234567890',
        preview: 'BTC swings 9% — now at 72%',
        ts: new Date().toISOString(),
      },
      {
        ticker: 'KXTRUMP-2026',
        category: 'Politics',
        action: 'prob_cross',
        telegram: true,
        tweet_id: null,
        preview: 'Trump 2026 crosses 60%',
        ts: new Date().toISOString(),
      },
    ],
    category_cooldowns: { Trending: 0, Crypto: 120 },
  },
  twitter: { enabled: true, recent_tweets: 12, last_post_time: Date.now() / 1000 },
  telegram: { enabled: true, recent_messages: 15 },
};

const MOCK_PIPELINE_STOPPED = {
  ...MOCK_PIPELINE_RUNNING,
  pipeline: { ...MOCK_PIPELINE_RUNNING.pipeline, running: false, total_emitted: 0 },
  news_agent: { ...MOCK_PIPELINE_RUNNING.news_agent, recent_posts: [] },
};

function setupMocks(data: unknown = MOCK_PIPELINE_RUNNING) {
  const refetch = jest.fn();
  mockUseApiData.mockReturnValue({ data, loading: false, refetch });
  return refetch;
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('PublishPipelinePanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({}) });
  });

  describe('Loading state', () => {
    it('shows skeleton when loading with no data', () => {
      mockUseApiData.mockReturnValue({ data: null, loading: true, refetch: jest.fn() });
      render(<PublishPipelinePanel />);
      // Skeleton renders no recognisable text — just verify nothing meaningful is shown
      expect(screen.queryByText('LIVE')).not.toBeInTheDocument();
      expect(screen.queryByText('STOPPED')).not.toBeInTheDocument();
    });
  });

  describe('Header & status', () => {
    it('shows LIVE badge when pipeline is running', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('shows STOPPED badge when pipeline is not running', () => {
      setupMocks(MOCK_PIPELINE_STOPPED);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('STOPPED')).toBeInTheDocument();
    });

    it('shows Telegram enabled with message count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText(/Telegram \(15 sent\)/)).toBeInTheDocument();
    });

    it('shows X/Twitter enabled with post count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText(/X\/Twitter \(12 posted\)/)).toBeInTheDocument();
    });

    it('shows tracked tickers count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('42 tickers tracked')).toBeInTheDocument();
    });

    it('shows throttled count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('3 throttled')).toBeInTheDocument();
    });
  });

  describe('Stats row', () => {
    it('shows processed count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('18')).toBeInTheDocument();
    });

    it('shows telegram count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('15')).toBeInTheDocument();
    });

    it('shows X posts count', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('12')).toBeInTheDocument();
    });

    it('shows zero errors in green', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('0')).toBeInTheDocument();
    });
  });

  describe('Category breakdown', () => {
    it('shows top categories with counts', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      // Categories appear in both breakdown and recent posts — use getAllByText
      expect(screen.getAllByText(/Trending/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Politics/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Crypto/).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Recent posts', () => {
    it('shows recent post tickers', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('KXBTC-1H-T95000')).toBeInTheDocument();
      expect(screen.getByText('KXTRUMP-2026')).toBeInTheDocument();
    });

    it('shows action badge for swing', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('Swing')).toBeInTheDocument();
    });

    it('shows action badge for prob_cross', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('Cross')).toBeInTheDocument();
    });

    it('shows post preview text', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('BTC swings 9% — now at 72%')).toBeInTheDocument();
    });

    it('shows empty state when no posts', () => {
      setupMocks(MOCK_PIPELINE_STOPPED);
      render(<PublishPipelinePanel />);
      expect(screen.getByText(/No posts yet/)).toBeInTheDocument();
    });

    it('renders tweet link when tweet_id present', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      const tweetLink = screen.getByRole('link', { name: /View tweet 1234567890/i });
      expect(tweetLink).toHaveAttribute('href', 'https://x.com/i/web/status/1234567890');
    });
  });

  describe('Category cooldowns', () => {
    it('shows cooldowns section toggle', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('Category cooldowns')).toBeInTheDocument();
    });

    it('expands cooldowns on click', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      fireEvent.click(screen.getByText('Category cooldowns'));
      expect(screen.getByText('ready')).toBeInTheDocument();  // Trending: 0 → ready
      expect(screen.getByText('120s')).toBeInTheDocument();   // Crypto: 120s
    });
  });

  describe('Manual trigger', () => {
    it('renders ticker input and category select', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByPlaceholderText('TICKER')).toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: /Select category/i })).toBeInTheDocument();
    });

    it('Fire button is disabled when ticker is empty', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      expect(screen.getByText('Fire').closest('button')).toBeDisabled();
    });

    it('Fire button enables when ticker is typed', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      fireEvent.change(screen.getByPlaceholderText('TICKER'), { target: { value: 'KXBTC' } });
      expect(screen.getByText('Fire').closest('button')).not.toBeDisabled();
    });

    it('uppercases ticker input', () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      const input = screen.getByPlaceholderText('TICKER');
      fireEvent.change(input, { target: { value: 'kxbtc' } });
      expect((input as HTMLInputElement).value).toBe('KXBTC');
    });

    it('fires POST to trigger endpoint with ticker and category', async () => {
      const refetch = setupMocks(MOCK_PIPELINE_RUNNING);
      (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => ({}) });
      render(<PublishPipelinePanel />);
      fireEvent.change(screen.getByPlaceholderText('TICKER'), { target: { value: 'KXBTC' } });
      fireEvent.click(screen.getByText('Fire'));
      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringContaining('ticker=KXBTC'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
      expect(refetch).toHaveBeenCalled();
    });

    it('shows success message after trigger', async () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => ({}) });
      render(<PublishPipelinePanel />);
      fireEvent.change(screen.getByPlaceholderText('TICKER'), { target: { value: 'KXBTC' } });
      fireEvent.click(screen.getByText('Fire'));
      await screen.findByText(/✓ Triggered KXBTC/);
    });

    it('shows error message when trigger fails', async () => {
      setupMocks(MOCK_PIPELINE_RUNNING);
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Pipeline not running' }),
      });
      render(<PublishPipelinePanel />);
      fireEvent.change(screen.getByPlaceholderText('TICKER'), { target: { value: 'KXBTC' } });
      fireEvent.click(screen.getByText('Fire'));
      await screen.findByText(/Pipeline not running/);
    });
  });

  describe('Refresh button', () => {
    it('calls refetch when refresh clicked', () => {
      const refetch = setupMocks(MOCK_PIPELINE_RUNNING);
      render(<PublishPipelinePanel />);
      fireEvent.click(screen.getByRole('button', { name: /Refresh pipeline status/i }));
      expect(refetch).toHaveBeenCalled();
    });
  });
});
