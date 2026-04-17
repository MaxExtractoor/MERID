const fs = require('fs');
const path = require('path');

function readUsedIcons() {
    const content = fs.readFileSync('used_icons.txt', 'utf-8');
    const lines = content.split('\n').filter(line => line.trim() && !line.includes('===') && !line.includes('Total'));
    return new Set(lines);
}

function readCurrentIcons() {
    const content = fs.readFileSync('src/ui/icons.ts', 'utf-8');
    
    // Extract imports from lucide-react
    const importMatch = content.match(/import\s*\{([^}]+)\}\s*from\s*['"]lucide-react['"]/);
    if (!importMatch) {
        throw new Error('Could not find lucide-react imports');
    }
    
    const importStatement = importMatch[1];
    const icons = importStatement.split(',').map(icon => icon.trim());
    
    // Extract exports - look for the direct export section
    const exportMatch = content.match(/export\s*\{([^}]+)\}/s);
    if (!exportMatch) {
        throw new Error('Could not find lucide-react exports');
    }
    
    const exportStatement = exportMatch[1];
    const exports = exportStatement.split(',').map(icon => icon.trim());
    
    return { icons, exports };
}

function generatePrunedIcons(usedIcons, currentIcons) {
    const usedIconNames = Array.from(usedIcons).filter(name => name !== 'getIcon' && name !== 'Icon');
    
    // Filter current imports to only include used icons
    const prunedImports = currentIcons.icons.filter(icon => {
        // Handle aliases like "X as LucideX"
        const iconName = icon.includes(' as ') ? icon.split(' as ')[1].trim() : icon;
        return usedIconNames.includes(iconName);
    });
    
    // Filter current exports to only include used icons
    const prunedExports = currentIcons.exports.filter(icon => {
        // Handle aliases like "LucideX as X"
        const exportName = icon.includes(' as ') ? icon.split(' as ')[1].trim() : icon;
        return usedIconNames.includes(exportName);
    });
    
    return {
        imports: prunedImports,
        exports: prunedExports,
        removed: currentIcons.icons.length - prunedImports.length
    };
}

function main() {
    const usedIcons = readUsedIcons();
    const currentIcons = readCurrentIcons();
    const pruned = generatePrunedIcons(usedIcons, currentIcons);
    
    console.log(`Current icons: ${currentIcons.icons.length}`);
    console.log(`Used icons: ${usedIcons.size - 2}`); // -2 for getIcon and Icon
    console.log(`Can remove: ${pruned.removed} icons`);
    
    console.log('\nPruned imports:');
    pruned.imports.forEach(icon => console.log(`  ${icon}`));
    
    console.log('\nPruned exports:');
    pruned.exports.forEach(icon => console.log(`  ${icon}`));
    
    // Generate the new icons.ts content
    const iconsContent = fs.readFileSync('src/ui/icons.ts', 'utf-8');
    
    // Replace imports
    const newImports = `  ${pruned.imports.join(',\n  ')}`;
    const newContent = iconsContent.replace(
        /import\s*\{[^}]+\}\s*from\s*['"]lucide-react['"]/,
        `import {\n${newImports}\n} from 'lucide-react'`
    );
    
    // Replace exports
    const newExports = `  ${pruned.exports.join(',\n  ')}`;
    const finalContent = newContent.replace(
        /export\s*\{[^}]+\}/s,
        `export {\n${newExports}\n}`
    );
    
    // Write backup
    fs.writeFileSync('src/ui/icons.ts.backup', iconsContent);
    
    // Write pruned version
    fs.writeFileSync('src/ui/icons.ts', finalContent);
    
    console.log('\n✅ Pruned src/ui/icons.ts');
    console.log('📁 Backup saved to src/ui/icons.ts.backup');
    console.log(`📉 Removed ${pruned.removed} unused icons`);
}

if (require.main === module) {
    main();
}
