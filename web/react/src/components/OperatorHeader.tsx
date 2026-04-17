// React import not needed with modern JSX transform
import ExecutionGateStrip from './ExecutionGateStrip';
import DataHealthSummary from './DataHealthSummary';

export default function OperatorHeader() {
  return (
    <header className="flex flex-col gap-4">
      <ExecutionGateStrip />
      <DataHealthSummary />
    </header>
  );
}
