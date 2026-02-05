import { useState, useEffect } from 'react';
import { Twitter, Send, Heart, MessageCircle, Repeat2, TrendingUp, RefreshCw, AlertCircle } from 'lucide-react';

interface SocialPost {
  id: string;
  platform: 'twitter' | 'telegram';
  content: string;
  timestamp: string;
  author: string;
  likes: number;
  retweets: number;
  replies: number;
  sentiment: 'positive' | 'negative' | 'neutral';
  topics: string[];
  engagement_score: number;
}

interface ScheduledPost {
  id: string;
  content: string;
  scheduled_time: string;
  platform: 'twitter' | 'telegram';
  status: 'pending' | 'posted' | 'failed';
}

interface SocialMetrics {
  total_posts: number;
  total_engagement: number;
  avg_sentiment: number;
  top_topic: string;
  followers: number;
  growth_rate: number;
}

export default function Social() {
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[]>([]);
  const [metrics, setMetrics] = useState<SocialMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newPost, setNewPost] = useState('');
  const [activeTab, setActiveTab] = useState<'feed' | 'schedule' | 'analytics'>('feed');

  useEffect(() => {
    fetchSocialData();
    const interval = setInterval(fetchSocialData, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchSocialData = async () => {
    try {
      const response = await fetch('/api/v1/social/feed');
      if (response.ok) {
        const data = await response.json();
        setPosts(data.posts || []);
        setScheduledPosts(data.scheduled || []);
        setMetrics(data.metrics || null);
        setError(null);
      } else {
        throw new Error('Failed to fetch social data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setPosts([
        {
          id: '1',
          platform: 'twitter',
          content: '🚀 BTC just broke $105K! Our AI agents predicted this move 3 hours ago with 87% confidence. #Bitcoin #Trading',
          timestamp: new Date(Date.now() - 1800000).toISOString(),
          author: 'MERID Bot',
          likes: 342,
          retweets: 89,
          replies: 45,
          sentiment: 'positive',
          topics: ['BTC', 'Trading', 'AI'],
          engagement_score: 0.82,
        },
        {
          id: '2',
          platform: 'twitter',
          content: '⚠️ Risk Alert: Portfolio exposure to ETH approaching 30% limit. Rebalancing recommended. #RiskManagement',
          timestamp: new Date(Date.now() - 3600000).toISOString(),
          author: 'MERID Bot',
          likes: 156,
          retweets: 34,
          replies: 23,
          sentiment: 'neutral',
          topics: ['ETH', 'Risk', 'Portfolio'],
          engagement_score: 0.65,
        },
        {
          id: '3',
          platform: 'twitter',
          content: '📊 Weekly Performance: +12.5% returns, 68% win rate, Sharpe ratio 2.1. Outperforming market by 8.3%. #Performance',
          timestamp: new Date(Date.now() - 7200000).toISOString(),
          author: 'MERID Bot',
          likes: 523,
          retweets: 145,
          replies: 67,
          sentiment: 'positive',
          topics: ['Performance', 'Trading', 'Stats'],
          engagement_score: 0.91,
        },
      ]);
      setScheduledPosts([
        {
          id: '1',
          content: '🔮 Market prediction for tomorrow: BTC consolidation expected around $104K-$106K range.',
          scheduled_time: new Date(Date.now() + 3600000).toISOString(),
          platform: 'twitter',
          status: 'pending',
        },
        {
          id: '2',
          content: '📈 Daily summary will be posted at 5 PM EST with full performance metrics.',
          scheduled_time: new Date(Date.now() + 7200000).toISOString(),
          platform: 'twitter',
          status: 'pending',
        },
      ]);
      setMetrics({
        total_posts: 247,
        total_engagement: 15420,
        avg_sentiment: 0.72,
        top_topic: 'BTC',
        followers: 3420,
        growth_rate: 8.5,
      });
    } finally {
      setLoading(false);
    }
  };

  const handlePostSubmit = async () => {
    if (!newPost.trim()) return;
    
    try {
      const response = await fetch('/api/v1/social/post', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newPost, platform: 'twitter' }),
      });
      
      if (response.ok) {
        setNewPost('');
        fetchSocialData();
      }
    } catch (err) {
      console.error('Failed to post:', err);
    }
  };

  const getSentimentColor = (sentiment: string) => {
    switch (sentiment) {
      case 'positive': return 'text-green-400';
      case 'negative': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getSentimentIcon = (sentiment: string) => {
    switch (sentiment) {
      case 'positive': return '😊';
      case 'negative': return '😟';
      default: return '😐';
    }
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading social feed...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Twitter className="w-8 h-8 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Social Feed</h1>
            <p className="text-sm text-gray-400">X (Twitter) bot integration and analytics</p>
          </div>
        </div>
        <button
          onClick={fetchSocialData}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Metrics Cards */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Total Posts</p>
            <p className="text-2xl font-bold text-white">{metrics.total_posts}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Engagement</p>
            <p className="text-2xl font-bold text-white">{metrics.total_engagement.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Avg Sentiment</p>
            <p className="text-2xl font-bold text-green-400">{(metrics.avg_sentiment * 100).toFixed(0)}%</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Top Topic</p>
            <p className="text-2xl font-bold text-white">{metrics.top_topic}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Followers</p>
            <p className="text-2xl font-bold text-white">{metrics.followers.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Growth Rate</p>
            <p className="text-2xl font-bold text-green-400">+{metrics.growth_rate}%</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['feed', 'schedule', 'analytics'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Feed Tab */}
      {activeTab === 'feed' && (
        <div className="space-y-6">
          {/* New Post */}
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <h3 className="text-white font-semibold mb-3">Create Post</h3>
            <textarea
              value={newPost}
              onChange={(e) => setNewPost(e.target.value)}
              placeholder="What's happening in the markets?"
              className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              rows={3}
            />
            <div className="flex items-center justify-between mt-3">
              <span className="text-sm text-gray-400">{newPost.length}/280 characters</span>
              <button
                onClick={handlePostSubmit}
                disabled={!newPost.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-gray-500 text-white rounded-lg flex items-center gap-2 transition-colors"
              >
                <Send className="w-4 h-4" />
                Post
              </button>
            </div>
          </div>

          {/* Posts Feed */}
          <div className="space-y-4">
            {posts.map(post => (
              <div key={post.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center">
                    <Twitter className="w-5 h-5 text-white" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <p className="text-white font-semibold">{post.author}</p>
                        <p className="text-sm text-gray-400">{formatTimestamp(post.timestamp)}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-sm ${getSentimentColor(post.sentiment)}`}>
                          {getSentimentIcon(post.sentiment)}
                        </span>
                        <span className="text-sm text-gray-400">
                          {(post.engagement_score * 100).toFixed(0)}% engagement
                        </span>
                      </div>
                    </div>
                    <p className="text-white mb-3">{post.content}</p>
                    <div className="flex items-center gap-2 mb-3">
                      {post.topics.map(topic => (
                        <span key={topic} className="px-2 py-1 bg-blue-500/20 text-blue-400 text-xs rounded">
                          #{topic}
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-6 text-gray-400">
                      <div className="flex items-center gap-2 hover:text-red-400 cursor-pointer transition-colors">
                        <Heart className="w-4 h-4" />
                        <span className="text-sm">{post.likes}</span>
                      </div>
                      <div className="flex items-center gap-2 hover:text-green-400 cursor-pointer transition-colors">
                        <Repeat2 className="w-4 h-4" />
                        <span className="text-sm">{post.retweets}</span>
                      </div>
                      <div className="flex items-center gap-2 hover:text-blue-400 cursor-pointer transition-colors">
                        <MessageCircle className="w-4 h-4" />
                        <span className="text-sm">{post.replies}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Schedule Tab */}
      {activeTab === 'schedule' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-gray-400">{scheduledPosts.length} scheduled posts</p>
            <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors">
              Schedule New Post
            </button>
          </div>

          {scheduledPosts.map(post => (
            <div key={post.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <p className="text-white mb-2">{post.content}</p>
                  <p className="text-sm text-gray-400">
                    Scheduled for: {new Date(post.scheduled_time).toLocaleString()}
                  </p>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  post.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                  post.status === 'posted' ? 'bg-green-500/20 text-green-400' :
                  'bg-red-500/20 text-red-400'
                }`}>
                  {post.status}
                </span>
              </div>
              <div className="flex gap-2">
                <button className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded transition-colors">
                  Edit
                </button>
                <button className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-sm rounded transition-colors">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Analytics Tab */}
      {activeTab === 'analytics' && (
        <div className="space-y-6">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
            <h3 className="text-lg font-bold text-white mb-4">Engagement Trends</h3>
            <div className="space-y-3">
              {['Likes', 'Retweets', 'Replies', 'Impressions'].map((metric, index) => {
                const value = [342, 89, 45, 1250][index];
                const percentage = (value / 1250) * 100;
                return (
                  <div key={metric}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="text-gray-400">{metric}</span>
                      <span className="text-white font-medium">{value}</span>
                    </div>
                    <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
            <h3 className="text-lg font-bold text-white mb-4">Top Performing Posts</h3>
            <div className="space-y-3">
              {posts.slice(0, 3).map((post, index) => (
                <div key={post.id} className="flex items-center gap-3 p-3 bg-slate-900/50 rounded">
                  <div className="flex items-center justify-center w-8 h-8 bg-blue-600 rounded-full text-white font-bold">
                    {index + 1}
                  </div>
                  <div className="flex-1">
                    <p className="text-white text-sm line-clamp-1">{post.content}</p>
                    <p className="text-xs text-gray-400">{post.likes + post.retweets + post.replies} total engagement</p>
                  </div>
                  <TrendingUp className="w-5 h-5 text-green-400" />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
