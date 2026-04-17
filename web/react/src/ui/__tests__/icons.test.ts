/**
 * Icon centralization test - ensures lucide-react is only imported in icons.ts
 */

import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

function findFiles(dir: string): string[] {
  const files: string[] = [];
  
  function traverse(currentDir: string) {
    const items = readdirSync(currentDir);
    
    for (const item of items) {
      const fullPath = join(currentDir, item);
      const stat = require('fs').statSync(fullPath);
      
      if (stat.isDirectory() && !item.startsWith('.') && item !== 'node_modules') {
        traverse(fullPath);
      } else if (item.endsWith('.ts') || item.endsWith('.tsx')) {
        files.push(fullPath);
      }
    }
  }
  
  traverse(dir);
  return files;
}

describe('Icon Centralization', () => {
  test('lucide-react imports only exist in icons.ts', () => {
    const srcDir = join(__dirname, '../..');
    const tsxFiles = findFiles(srcDir);
    
    const violations: string[] = [];
    
    for (const file of tsxFiles) {
      // Skip the icons.ts file itself
      if (file.includes('icons.ts')) continue;
      
      // Skip test files
      if (file.includes('.test.') || file.includes('__tests__')) continue;
      
      const content = readFileSync(file, 'utf-8');
      
      // Look for direct lucide-react imports
      if (content.includes("from 'lucide-react'") || 
          content.includes('from "lucide-react"') ||
          content.includes("from 'lucide-react/dist'") ||
          content.includes('from "lucide-react/dist"')) {
        violations.push(file);
      }
    }
    
    expect(violations).toEqual([]);
    
    if (violations.length > 0) {
      console.error('Files with direct lucide-react imports:');
      violations.forEach(file => console.error(`  - ${file}`));
    }
  });
  
  test('icons.ts exports all commonly used icons', () => {
    const iconsFile = join(__dirname, '../icons.ts');
    const content = readFileSync(iconsFile, 'utf-8');
    
    // Check that essential icons are exported
    const essentialIcons = [
      'X', 'ChevronLeft', 'ChevronRight', 'Search', 'Settings',
      'Shield', 'AlertTriangle', 'Activity', 'TrendingUp', 'RefreshCw'
    ];
    
    for (const icon of essentialIcons) {
      expect(content).toContain(icon);
    }
  });
});
