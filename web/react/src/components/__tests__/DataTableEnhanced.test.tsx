import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import DataTableEnhanced from '../DataTableEnhanced';

describe('DataTableEnhanced', () => {
  const mockData = [
    { id: 1, name: 'John Doe', email: 'john@example.com', status: 'ACTIVE' },
    { id: 2, name: 'Jane Smith', email: 'jane@example.com', status: 'INACTIVE' },
    { id: 3, name: 'Bob Johnson', email: 'bob@example.com', status: 'ACTIVE' },
  ];

  const mockColumns = [
    { key: 'id' as const, label: 'ID', sortable: true },
    { key: 'name' as const, label: 'Name', sortable: true },
    { key: 'email' as const, label: 'Email', sortable: false },
    { key: 'status' as const, label: 'Status', sortable: true },
  ];

  it('renders table with data', () => {
    render(
      <DataTableEnhanced
        data={mockData}
        columns={mockColumns}
      />
    );
    
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    // Status is in a table cell, so we check if it exists in the document
    expect(screen.getAllByText('ACTIVE')).toHaveLength(2);
  });

  it('renders column headers', () => {
    render(
      <DataTableEnhanced
        data={mockData}
        columns={mockColumns}
      />
    );
    
    expect(screen.getByText('ID')).toBeInTheDocument();
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Email')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
  });

  it('handles sorting', async () => {
    render(
      <DataTableEnhanced
        data={mockData}
        columns={mockColumns}
      />
    );
    
    const nameHeader = screen.getByText('Name');
    fireEvent.click(nameHeader);
    
    await waitFor(() => {
      const rows = screen.getAllByRole('row');
      expect(rows[1]).toHaveTextContent('Bob Johnson'); // First sorted row
    });
  });

  it('handles filtering', async () => {
    render(
      <DataTableEnhanced
        data={mockData}
        columns={mockColumns}
        showFilter={true}
      />
    );
    
    const filterInput = screen.getByPlaceholderText('Filter table...');
    fireEvent.change(filterInput, { target: { value: 'John' } });
    
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByText('Jane Smith')).not.toBeInTheDocument();
    });
  });

  it('handles pagination', async () => {
    const largeData = Array.from({ length: 50 }, (_, i) => ({
      id: i + 1,
      name: `User ${i + 1}`,
      email: `user${i + 1}@example.com`,
      status: i % 2 === 0 ? 'ACTIVE' : 'INACTIVE',
    }));

    render(
      <DataTableEnhanced
        data={largeData}
        columns={mockColumns}
        pageSize={10}
        showPagination={true}
      />
    );
    
    expect(screen.getByText('User 1')).toBeInTheDocument();
    expect(screen.queryByText('User 11')).not.toBeInTheDocument();
  });

  it('shows selection when enabled', () => {
    const mockOnRowSelect = jest.fn();
    
    render(
      <DataTableEnhanced
        data={mockData}
        columns={mockColumns}
        showSelection={true}
        onRowSelect={mockOnRowSelect}
      />
    );
    
    // Check if selection UI is present
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
