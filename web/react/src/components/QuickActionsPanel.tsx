import React from 'react';

const QuickActionsPanel: React.FC = () => (
  <div className="quick-actions-panel" />
);

const MemoizedQuickActionsPanel = React.memo(QuickActionsPanel);
MemoizedQuickActionsPanel.displayName = 'QuickActionsPanel';
export default MemoizedQuickActionsPanel;
