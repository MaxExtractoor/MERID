import React from 'react';

const DataTable: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <table className="data-table"><tbody>{children}</tbody></table>
);

const MemoizedDataTable = React.memo(DataTable);
MemoizedDataTable.displayName = 'DataTable';
export default MemoizedDataTable;
