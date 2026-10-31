export type NavKey = 'dashboard' | 'analyzer' | 'large-files' | 'duplicates' | 'cleanup' | 'insights' | 'history' | 'settings'

export const navItems = [
  { key: 'dashboard', label: 'Dashboard', icon: 'LayoutDashboard' },
  { key: 'analyzer', label: 'Disk Analyzer', icon: 'ScanSearch' },
  { key: 'large-files', label: 'Large Files', icon: 'Files' },
  { key: 'duplicates', label: 'Duplicates', icon: 'CopyCheck' },
  { key: 'cleanup', label: 'Cleanup Center', icon: 'Sparkles' },
  { key: 'insights', label: 'File Insights', icon: 'ChartNoAxesCombined' },
  { key: 'history', label: 'Scan History', icon: 'History' },
] as const

export const storageCategories = [
  { name: 'Videos', size: '152.3 GB', percent: 32.4, color: '#e86b38' },
  { name: 'Games', size: '98.7 GB', percent: 21.1, color: '#d946ef' },
  { name: 'System files', size: '76.1 GB', percent: 16.2, color: '#22c55e' },
  { name: 'Applications', size: '54.4 GB', percent: 11.6, color: '#eab308' },
  { name: 'Images', size: '42.1 GB', percent: 9.0, color: '#3b82f6' },
  { name: 'Documents', size: '28.4 GB', percent: 6.1, color: '#06b6d4' },
  { name: 'Archives', size: '16.6 GB', percent: 3.5, color: '#8b5cf6' },
  { name: 'Other', size: '10.6 GB', percent: 2.2, color: '#64748b' },
]

export const largestFiles = [
  { name: 'Ubuntu 64-bit.vmdk', size: '10.1 GB', type: 'vmdk', path: 'F:/Games/Cyberpunk_2077/Virtual', modified: '12 Oct 2026' },
  { name: 'ISC_3020_Training_ProRes.mov', size: '9.8 GB', type: 'mov', path: 'C:/Users/Casey/Videos', modified: '10 Oct 2026' },
  { name: 'pagefile.sys', size: '8.0 GB', type: 'sys', path: 'C:/', modified: '08 Oct 2026' },
  { name: 'patchwork-10-WindowsClient.zip', size: '7.6 GB', type: 'zip', path: 'F:/Art Games/VALORANT', modified: '01 Oct 2026' },
  { name: 'Windows.iso', size: '12.8 GB', type: 'iso', path: 'F:/ISOs', modified: '30 Sep 2026' },
]

export const folders = [
  { name: 'Users', size: '421.3 GB', percent: '88.3%', children: ['Casey', 'Public', 'Default'] },
  { name: 'Program Files', size: '94.8 GB', percent: '19.8%', children: ['Common Files', 'WindowsApps'] },
  { name: 'Windows', size: '76.4 GB', percent: '16.0%', children: ['System32', 'Installer'] },
  { name: 'Program Files (x86)', size: '43.0 GB', percent: '9.0%', children: ['Common Files'] },
  { name: 'ProgramData', size: '21.7 GB', percent: '4.5%', children: ['Microsoft', 'Package Cache'] },
  { name: 'Games', size: '18.9 GB', percent: '4.0%', children: ['SteamLibrary', 'Riot Games'] },
  { name: 'Recovery', size: '6.1 GB', percent: '1.3%', children: [] },
]

export const history = [
  { date: '17 Oct 2026', drive: 'C:', scan: 'Quick Scan', files: '811,544', size: '392.4 GB', duration: '00:32', status: 'Completed' },
  { date: '15 Oct 2026', drive: 'F:', scan: 'Full Scan', files: '99,221', size: '377.6 GB', duration: '04:12', status: 'Completed' },
  { date: '12 Oct 2026', drive: 'F:', scan: 'Quick Scan', files: '581,221', size: '415.8 GB', duration: '01:08', status: 'Completed' },
  { date: '09 Oct 2026', drive: 'C:', scan: 'Quick Scan', files: '98,112', size: '372.0 GB', duration: '00:44', status: 'Completed' },
  { date: '05 Oct 2026', drive: 'C:', scan: 'Full Scan', files: '612,145', size: '390.4 GB', duration: '02:56', status: 'Completed' },
]

export const cleanupItems = [
  { name: 'Windows Temp Files', size: '2.3 GB', count: '1,284 items', risk: 'Low', desc: 'Temporary files created by Windows and installers.' },
  { name: 'Browser Cache', size: '1.1 GB', count: '8,901 items', risk: 'Low', desc: 'Cached web resources that can be downloaded again.' },
  { name: 'Windows Update Cache', size: '4.8 GB', count: '223 items', risk: 'Review', desc: 'Previous update packages retained for rollback.' },
  { name: 'Recycle Bin', size: '3.2 GB', count: '64 items', risk: 'Review', desc: 'Files already marked for deletion.' },
  { name: 'Thumbnail Cache', size: '512 MB', count: '3,228 items', risk: 'Low', desc: 'Preview images regenerated automatically as needed.' },
  { name: 'Delivery Optimization', size: '1.6 GB', count: '89 items', risk: 'Low', desc: 'Peer-to-peer Windows update delivery files.' },
]
