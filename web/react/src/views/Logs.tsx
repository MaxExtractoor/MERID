/**
 * Logs View — System Logs
 */

import { FileText } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';

const Logs = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <FileText className="w-8 h-8 text-cyan-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Logs</h1>
          <p className="text-sm text-slate-400">System logs and activity</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Logs View</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-slate-400">
            <p>Logs view coming soon</p>
            <p className="text-sm mt-2">This view will display system logs and activity history.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Logs;
