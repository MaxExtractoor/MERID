import { useState, useMemo } from 'react';
import { Twitter, Send, Heart, MessageCircle, Repeat2, TrendingUp, RefreshCw, AlertCircle, Filter, Bot, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';
import StubBanner from '../components/StubBanner';

interface SocialPost {
  id: string;
  platform: 'twitter' | 'telegram' | 'internal';
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

interface SocialData {
  posts: SocialPost[];
  scheduled: ScheduledPost[];
  metrics: SocialMetrics | null;
  source?: string;
}

export default function Social() {
  const [newPost, setNewPost] = useState('');
  const [activeTab, setActiveTab] = useState<'feed' | 'schedule' | 'analytics'>('feed');
  const [topicFilter, setTopicFilter] = useState<string | null>(null);
  const [expandedPost, setExpandedPost] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

  const { data: rawData, loading, error, refetch } = useApiData<SocialData>(
    API_ENDPOINTS.SOCIAL_FEED,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );
  const posts = useMemo(() => rawData?.posts ?? [], [rawData]);
  const scheduledPosts = rawData?.scheduled ?? [];
  const metrics = rawData?.metrics ?? null;

  const allTopics = useMemo(() => {
    const topics = new Set<string>();
    posts.forEach(p => p.topics?.forEach(t => topics.add(t)));
    return Array.from(topics).sort();
  }, [posts]);

  const filteredPosts = useMemo(() => {
    let filtered = topicFilter
      ? posts.filter(p => p.topics?.includes(topicFilter))
      : posts;
    if (sortOrder === 'oldest') filtered = [...filtered].reverse();
    return filtered;
  }, [posts, topicFilter, sortOrder]);

  const handlePostSubmit = async () => {
    if (!newPost.trim()) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.SOCIAL_POST, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newPost, platform: 'twitter' }),
      });
      
      if (response.ok) {
        setNewPost('');
        refetch();
      }
    } catch {
      // Post failed — UI state unchanged
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
      <StubBanner data={rawData} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Twitter className="w-8 h-8 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Activity Feed</h1>
            <p className="text-sm text-gray-400">Agent activity log & system events</p>
          </div>
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
         title="fetch Social Data">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Metrics Cards */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Total Events</p>
            <p className="text-2xl font-bold text-white">{metrics.total_posts}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Avg Sentiment</p>
            <p className="text-2xl font-bold text-green-400">{(metrics.avg_sentiment * 100).toFixed(0)}%</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Top Topic</p>
            <p className="text-2xl font-bold text-white">{metrics.top_topic}</p>
          </div>
          {metrics.followers > 0 && (
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
              <p className="text-sm text-gray-400 mb-1">Followers</p>
              <p className="text-2xl font-bold text-white">{metrics.followers.toLocaleString()}</p>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-slate-700">
        <div className="flex gap-2">
          {(['feed', 'schedule', 'analytics'] as const).map(tab => (
            <button type="button"
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
        {activeTab === 'feed' && (
          <div className="flex items-center gap-2 pb-2">
            <button type="button"
              onClick={() => setSortOrder(sortOrder === 'newest' ? 'oldest' : 'newest')}
              className="flex items-center gap-1 px-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-xs text-slate-400 hover:text-white transition-colors"
              title="Toggle sort order"
            >
              <Clock className="w-3 h-3" />
              {sortOrder === 'newest' ? 'Newest' : 'Oldest'}
              {sortOrder === 'newest' ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
            </button>
          </div>
        )}
      </div>

      {/* Feed Tab */}
      {activeTab === 'feed' && (
        <div className="space-y-6">
          {/* Topic Filters */}
          {allTopics.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <Filter className="w-4 h-4 text-slate-400" />
              <button type="button"
                onClick={() => setTopicFilter(null)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                  topicFilter === null
                    ? 'bg-blue-500/30 text-blue-400 border border-blue-500/50'
                    : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:border-slate-600'
                }`}
              >
                All
              </button>
              {allTopics.map(topic => (
                <button type="button"
                  key={topic}
                  onClick={() => setTopicFilter(topicFilter === topic ? null : topic)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                    topicFilter === topic
                      ? 'bg-purple-500/30 text-purple-400 border border-purple-500/50'
                      : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:border-slate-600'
                  }`}
                >
                  #{topic}
                </button>
              ))}
            </div>
          )}

          {/* New Post */}
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <h3 className="text-white font-semibold mb-3">Create Post</h3>
            <textarea aria-label="Text input"
              id="social-new-post"
              name="newPost"
              value={newPost}
              onChange={(e) => setNewPost(e.target.value)}
              placeholder="What's happening in the markets?"
              className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              rows={3}
            />
            <div className="flex items-center justify-between mt-3">
              <span className="text-sm text-gray-400">{newPost.length}/280 characters</span>
              <button type="button"
                onClick={handlePostSubmit}
                disabled={!newPost.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-gray-500 text-white rounded-lg flex items-center gap-2 transition-colors"
               title="Post Submit">
                <Send className="w-4 h-4" />
                Post
              </button>
            </div>
          </div>

          {/* Posts Feed - Timeline Style */}
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-5 top-0 bottom-0 w-px bg-gradient-to-b from-blue-500/50 via-purple-500/30 to-transparent" />
            
            <div className="space-y-4">
              {filteredPosts.map((post, idx) => (
                <div 
                  key={post.id} 
                  className="relative pl-12 group"
                  style={{ animationDelay: `${idx * 50}ms` }}
                >
                  {/* Timeline dot */}
                  <div className={`absolute left-3.5 top-5 w-3 h-3 rounded-full border-2 transition-all duration-300 ${
                    post.sentiment === 'positive' 
                      ? 'bg-green-500 border-green-400 shadow-lg shadow-green-500/50' 
                      : post.sentiment === 'negative'
                        ? 'bg-red-500 border-red-400 shadow-lg shadow-red-500/50'
                        : 'bg-blue-500 border-blue-400 shadow-lg shadow-blue-500/50'
                  } group-hover:scale-150`} />
                  
                  <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4 hover:border-slate-600/70 hover:bg-slate-800/70 transition-all duration-200 cursor-pointer"
                       onClick={() => setExpandedPost(expandedPost === post.id ? null : post.id)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpandedPost(expandedPost === post.id ? null : post.id))(); } }}>
                    <div className="flex items-start gap-3">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                        post.platform === 'internal' ? 'bg-purple-600' : 'bg-blue-600'
                      }`}>
                        {post.platform === 'internal' 
                          ? <Bot className="w-5 h-5 text-white" />
                          : <Twitter className="w-5 h-5 text-white" />
                        }
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <p className="text-white font-semibold text-sm">{post.author}</p>
                            {post.platform === 'internal' && (
                              <span className="px-1.5 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded font-medium">Agent</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              post.sentiment === 'positive' ? 'bg-green-500/15 text-green-400'
                                : post.sentiment === 'negative' ? 'bg-red-500/15 text-red-400'
                                : 'bg-slate-500/15 text-slate-400'
                            }`}>
                              {getSentimentIcon(post.sentiment)} {post.sentiment}
                            </span>
                            <span className="text-xs text-slate-500">{formatTimestamp(post.timestamp)}</span>
                          </div>
                        </div>
                        <p className={`text-slate-200 text-sm leading-relaxed ${
                          expandedPost === post.id ? '' : 'line-clamp-2'
                        }`}>{post.content}</p>
                        
                        {/* Topics */}
                        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                          {(post.topics || []).map(topic => (
                            <span
                              key={topic}
                              role="button"
                              tabIndex={0}
                              onClick={(e) => { e.stopPropagation(); setTopicFilter(topicFilter === topic ? null : topic); }}
                              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); setTopicFilter(topicFilter === topic ? null : topic); } }}
                              className={`px-2 py-0.5 text-xs rounded transition-all cursor-pointer ${
                                topicFilter === topic
                                  ? 'bg-purple-500/30 text-purple-400 border border-purple-500/50'
                                  : 'bg-slate-700/50 text-slate-400 hover:text-blue-400'
                              }`}
                            >
                              #{topic}
                            </span>
                          ))}
                        </div>

                        {/* Engagement (if any) */}
                        {(post.likes > 0 || post.retweets > 0 || post.replies > 0) && (
                          <div className="flex items-center gap-5 mt-2 text-gray-500">
                            <div className="flex items-center gap-1.5 hover:text-red-400 cursor-pointer transition-colors">
                              <Heart className="w-3.5 h-3.5" />
                              <span className="text-xs">{post.likes}</span>
                            </div>
                            <div className="flex items-center gap-1.5 hover:text-green-400 cursor-pointer transition-colors">
                              <Repeat2 className="w-3.5 h-3.5" />
                              <span className="text-xs">{post.retweets}</span>
                            </div>
                            <div className="flex items-center gap-1.5 hover:text-blue-400 cursor-pointer transition-colors">
                              <MessageCircle className="w-3.5 h-3.5" />
                              <span className="text-xs">{post.replies}</span>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {filteredPosts.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <Filter className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No events matching filter</p>
              <button type="button" onClick={() => setTopicFilter(null)} className="text-blue-400 text-sm mt-1 hover:underline">Clear filter</button>
            </div>
          )}
        </div>
      )}

      {/* Schedule Tab */}
      {activeTab === 'schedule' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-gray-400">{scheduledPosts.length} scheduled posts</p>
            <button type="button" className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors" title="Schedule New Post">
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
                <button type="button" className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded transition-colors" title="Edit">
                  Edit
                </button>
                <button type="button" className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-sm rounded transition-colors" title="Delete">
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
