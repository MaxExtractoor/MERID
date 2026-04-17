const fs = require('fs');
const path = require('path');

function extractIconImports() {
    const srcDir = path.join(__dirname, 'src');
    const usedIcons = new Set();
    
    // Pattern to match icon imports from '../ui/icons'
    const pattern = /import\s*\{([^}]+)\}\s*from\s*['"]\.\.\/ui\/icons['"]/g;
    
    function processDirectory(dir) {
        const files = fs.readdirSync(dir);
        
        for (const file of files) {
            const filePath = path.join(dir, file);
            const stat = fs.statSync(filePath);
            
            if (stat.isDirectory()) {
                processDirectory(filePath);
            } else if (file.endsWith('.tsx') || file.endsWith('.ts')) {
                try {
                    const content = fs.readFileSync(filePath, 'utf-8');
                    let match;
                    
                    while ((match = pattern.exec(content)) !== null) {
                        const importStatement = match[1];
                        // Split by comma and clean up
                        const icons = importStatement.split(',').map(icon => icon.trim());
                        
                        for (const icon of icons) {
                            // Handle aliases like "Settings as SettingsIcon"
                            let cleanIcon = icon;
                            if (icon.includes(' as ')) {
                                cleanIcon = icon.split(' as ')[0].trim();
                            }
                            // Remove any remaining whitespace
                            cleanIcon = cleanIcon.trim();
                            if (cleanIcon) {
                                usedIcons.add(cleanIcon);
                            }
                        }
                    }
                } catch (error) {
                    console.error(`Error processing ${filePath}:`, error.message);
                }
            }
        }
    }
    
    processDirectory(srcDir);
    
    return Array.from(usedIcons).sort();
}

function main() {
    const usedIcons = extractIconImports();
    
    console.log('Icons actually used in the codebase:');
    console.log('='.repeat(50));
    usedIcons.forEach(icon => console.log(`  ${icon}`));
    
    console.log(`\nTotal unique icons used: ${usedIcons.length}`);
    
    // Write to file for easy reference
    const output = usedIcons.join('\n');
    fs.writeFileSync('used_icons.txt', `Icons actually used:\n${'='.repeat(30)}\n${output}\n\nTotal: ${usedIcons.length}\n`);
    
    console.log('\nWritten to used_icons.txt');
}

if (require.main === module) {
    main();
}
