import React from 'react';

const MarketsOverview: React.FC = () => (
  <div className="markets-overview" />
);

const MemoizedMarketsOverview = React.memo(MarketsOverview);
MemoizedMarketsOverview.displayName = 'MarketsOverview';
export default MemoizedMarketsOverview;
