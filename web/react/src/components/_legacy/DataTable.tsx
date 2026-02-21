interface DataTableProps {
  data: Record<string, unknown>[];
  columns: {
    key: string;
    label: string;
    render?: (value: unknown) => React.ReactNode;
  }[];
}

function DataTable({ data, columns }: DataTableProps) {
  return (
    <table className="w-full text-sm text-left border-collapse bg-slate-900/70 text-slate-100 dark:bg-slate-900/80">
      <thead className="bg-slate-800/80 text-xs uppercase text-slate-400 dark:bg-slate-800">
        <tr>
          {columns.map((col) => (
            <th key={col.key} className="px-3 py-2">
              {col.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row, index) => (
          <tr key={index} className="border-t border-slate-800/60 hover:bg-slate-800/60 dark:hover:bg-slate-700/60">
            {columns.map((col) => (
              <td key={col.key} className="px-3 py-2 text-slate-50">
                {col.render ? col.render(row[col.key]) : row[col.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Light theme variant
export function DataTableLight({ data, columns }: DataTableProps) {
  return (
    <table className="w-full text-sm text-left border-collapse bg-white text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <thead className="bg-slate-100 text-xs uppercase text-slate-600 dark:bg-slate-800 dark:text-slate-400">
        <tr>
          {columns.map((col) => (
            <th key={col.key} className="px-3 py-2">
              {col.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row, index) => (
          <tr key={index} className="border-t border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
            {columns.map((col) => (
              <td key={col.key} className="px-3 py-2">
                {col.render ? col.render(row[col.key]) : row[col.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const MemoizedDataTable = React.memo(DataTable);
MemoizedDataTable.displayName = 'DataTable';
export default MemoizedDataTable;
