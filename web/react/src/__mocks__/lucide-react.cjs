/**
 * Jest mock for lucide-react.
 *
 * lucide-react uses ESM-only exports that jest/ts-jest cannot resolve
 * in the jsdom test environment.  This mock generates a lightweight
 * forwardRef SVG stub for every icon name used in the codebase.
 */
'use strict';

// Delay React require so the mock object itself always builds
let _React;
function getReact() {
  if (!_React) _React = require('react');
  return _React;
}

function makeIcon(name) {
  const R = getReact();
  const Icon = R.forwardRef(function LucideIcon(props, ref) {
    return R.createElement('svg', Object.assign({}, props, { ref: ref, 'data-lucide': name }));
  });
  Icon.displayName = name;
  return Icon;
}

// Every icon name imported anywhere in src/ui/icons.ts or direct imports
var ICON_NAMES = [
  'ChevronLeft','ChevronRight','ChevronUp','ChevronDown','Menu','X',
  'Search','Filter','Settings','Home','Globe','LayoutDashboard','LayoutGrid',
  'Monitor','Shield','ShieldCheck','ShieldAlert','ShieldOff','AlertCircle',
  'TrendingUp','TrendingDown','DollarSign','Activity','BarChart3','Target',
  'Crosshair','Gauge','Zap','ZapOff','Briefcase','Wallet','CreditCard',
  'ArrowUpRight','ArrowDownRight','ArrowUp','ArrowDown','ArrowUpDown',
  'ToggleLeft','ToggleRight','Loader','Brain','Power','PowerOff',
  'Play','Pause','Square','RefreshCw','Download','Upload','Edit2','Trash2',
  'Plus','Minus','Check','Eye','EyeOff','Layers','Package','Sliders',
  'Clock','Wifi','WifiOff','AlertTriangle','AlertOctagon','CheckCircle',
  'CheckCircle2','XCircle','Info','Loader2','Users','User','Bot','Database',
  'HelpCircle','Server','PieChart','LineChart','AreaChart','Award','Trophy',
  'Star','Flame','Bookmark','Lightbulb','Calendar','CalendarDays','Timer',
  'Hourglass','MessageSquare','Bell','Send','Radio','Twitter','MessageCircle',
  'Volume2','VolumeX','ExternalLink','FileText','File','FileWarning','Folder',
  'FolderOpen','DownloadCloud','UploadCloud','Code','Terminal','GitBranch',
  'Cpu','HardDrive','Users2','UserPlus','UserCheck','UserX','Heart','Share',
  'Link','Lock','Unlock','Key','Fingerprint','Image','Video','Music','Camera',
  'Mic','MicOff','Truck','Plane','Ship','Car','Bike','Cloud','CloudRain',
  'CloudOff','Sun','Moon','Wind','Thermometer','Snowflake','Droplets',
  'MoreHorizontal','MoreVertical','Maximize2','Minimize2','Move','Copy',
  'Clipboard','Scissors','Hash','AtSign','Percent','Inbox','ArrowRight',
  'ArrowDownCircle','PauseCircle','RotateCcw','Grid','Sparkles','Wrench',
  'CircleDot','BarChart','BarChart2','Signal','Repeat','ChevronFirst',
  'ChevronLast','ChevronsLeft','ChevronsRight','ListFilter','SlidersHorizontal',
  'CircleAlert','TriangleAlert','ShieldQuestion','CircleHelp',
];

var i, exports = module.exports;
exports.__esModule = true;
for (i = 0; i < ICON_NAMES.length; i++) {
  exports[ICON_NAMES[i]] = makeIcon(ICON_NAMES[i]);
}
exports.createLucideIcon = function(name) { return makeIcon(name); };
