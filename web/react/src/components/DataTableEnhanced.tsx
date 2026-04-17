import React, { useState, useMemo } from "react";

interface Column<T> {
  key: keyof T;
  label: string;
  sortable?: boolean;
  render?: (value: unknown, row: T) => React.ReactNode;
  width?: string;
}

interface DataTableEnhancedProps<T> {
  data: T[];
  columns: Column<T>[];
  pageSize?: number;
  showPagination?: boolean;
  showFilter?: boolean;
  showSelection?: boolean;
  onRowSelect?: (selectedRows: T[]) => void;
  className?: string;
}

export default function DataTableEnhanced<T>({
  data,
  columns,
  pageSize = 25,
  showPagination = true,
  showFilter = true,
  showSelection = false,
  onRowSelect,
  className = "",
}: DataTableEnhancedProps<T>) {
  const [sortKey, setSortKey] = useState<keyof T | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [filterText, setFilterText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());

  // Filter data
  const filteredData = useMemo(() => {
    const dataArray = Array.isArray(data) ? data : [];
    if (!filterText) return dataArray;
    
    return dataArray.filter((row) =>
      columns.some((col) => {
        const value = row[col.key];
        return String(value).toLowerCase().includes(filterText.toLowerCase());
      })
    );
  }, [data, columns, filterText]);

  // Sort data
  const sortedData = useMemo(() => {
    if (!sortKey) return filteredData;

    return [...filteredData].sort((a, b) => {
      const aValue = a[sortKey];
      const bValue = b[sortKey];

      if (aValue === null || aValue === undefined) return 1;
      if (bValue === null || bValue === undefined) return -1;

      const comparison = aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      return sortDirection === "desc" ? -comparison : comparison;
    });
  }, [filteredData, sortKey, sortDirection]);

  // Paginate data
  const paginatedData = useMemo(() => {
    const dataArray = Array.isArray(sortedData) ? sortedData : [];
    if (!showPagination) return dataArray;

    const startIndex = (currentPage - 1) * pageSize;
    return dataArray.slice(startIndex, startIndex + pageSize);
  }, [sortedData, currentPage, pageSize, showPagination]);

  const totalPages = Math.ceil((Array.isArray(sortedData) ? sortedData.length : 0) / pageSize);

  const handleSort = (key: keyof T) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  const handleRowSelect = (index: number, checked: boolean) => {
    const newSelected = new Set(selectedRows);
    if (checked) {
      newSelected.add(index);
    } else {
      newSelected.delete(index);
    }
    setSelectedRows(newSelected);

    const selectedData = Array.from(newSelected).map((i) => sortedData[i]);
    onRowSelect?.(selectedData);
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      const allIndices = new Set(paginatedData.map((_, i) => i));
      setSelectedRows(allIndices);
      onRowSelect?.(paginatedData);
    } else {
      setSelectedRows(new Set());
      onRowSelect?.([]);
    }
  };

  const getSortIcon = (column: Column<T>) => {
    if (!column.sortable || sortKey !== column.key) {
      return null;
    }
    return sortDirection === "asc" ? "↑" : "↓";
  };

  return (
    <div className={`data-table-enhanced ${className}`}>
      {/* Filter */}
      {showFilter && (
        <div className="mb-4">
          <input aria-label="Filter Text"
            id="data-table-filter"
            name="tableFilter"
            type="text"
            placeholder="Filter table..."
            title="Filter table data"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
          />
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left border-collapse bg-slate-900/70 text-slate-100">
          <thead className="bg-slate-800/80 text-xs uppercase text-slate-400">
            <tr>
              {showSelection && (
                <th className="px-3 py-2">
                  <input aria-label="Input field"
                    type="checkbox"
                    title="Select all rows"
                    checked={selectedRows.size === paginatedData.length && paginatedData.length > 0}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={String(col.key)}
                  className={`px-3 py-2 ${col.sortable ? "cursor-pointer hover:bg-slate-700" : ""}`}
                  style={{ width: col.width }}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  <div className="flex items-center gap-1">
                    {col.label}
                    {getSortIcon(col)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedData.map((row, index) => {
              // Try to use a unique identifier from the row if available
              const rowKey = String((row as Record<string, unknown>).id ?? (row as Record<string, unknown>).symbol ?? `row-${index}`);
              return (
                <tr
                  key={rowKey}
                  className={`border-t border-slate-800/60 hover:bg-slate-800/60 ${
                    selectedRows.has(index) ? "bg-slate-700/40" : ""
                  }`}
                >
                {showSelection && (
                  <td className="px-3 py-2">
                    <input aria-label="Input field"
                      type="checkbox"
                      title={`Select row ${index + 1}`}
                      checked={selectedRows.has(index)}
                      onChange={(e) => handleRowSelect(index, e.target.checked)}
                      className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                    />
                  </td>
                )}
                {columns.map((col) => (
                  <td key={String(col.key)} className="px-3 py-2 text-slate-50">
                    {col.render ? col.render(row[col.key], row) : String(row[col.key] ?? "")}
                  </td>
                ))}
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {showPagination && totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <div className="text-sm text-slate-400">
            Showing {((currentPage - 1) * pageSize) + 1} to{" "}
            {Math.min(currentPage * pageSize, sortedData.length)} of{" "}
            {sortedData.length} entries
          </div>
          
          <div className="flex items-center gap-2">
            <button type="button"
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
              className="px-3 py-1 bg-slate-700 border border-slate-600 rounded text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-600"
            >
              Previous
            </button>
            
            <span className="text-sm text-slate-400">
              Page {currentPage} of {totalPages}
            </span>
            
            <button type="button"
              onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
              disabled={currentPage === totalPages}
              className="px-3 py-1 bg-slate-700 border border-slate-600 rounded text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-600"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
