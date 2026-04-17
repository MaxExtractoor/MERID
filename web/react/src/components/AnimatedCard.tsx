import React from 'react';

const AnimatedCard: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <div className="animated-card">{children}</div>
);

const MemoizedAnimatedCard = React.memo(AnimatedCard);
MemoizedAnimatedCard.displayName = 'AnimatedCard';
export default MemoizedAnimatedCard;
