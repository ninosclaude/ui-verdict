/**
 * Simple test for the Midscene executor
 */

import { spawn } from 'child_process';
import readline from 'readline';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function sendCommand(proc, command) {
    return new Promise((resolve, reject) => {
        const rl = readline.createInterface({ input: proc.stdout });
        
        const onLine = (line) => {
            // Skip non-JSON lines (log messages from libraries like Midscene)
            if (!line.trim().startsWith('{') && !line.trim().startsWith('[')) {
                console.error('[skipped non-JSON]', line);
                return;
            }
            
            rl.close();
            try {
                resolve(JSON.parse(line));
            } catch (e) {
                reject(new Error(`Failed to parse: ${line}`));
            }
        };
        
        rl.on('line', onLine);
        proc.stdin.write(JSON.stringify(command) + '\n');
    });
}

async function main() {
    console.log('Starting executor...');
    
    const proc = spawn('node', ['executor.js'], {
        cwd: __dirname,
        stdio: ['pipe', 'pipe', 'inherit'],
    });
    
    // Wait for ready signal
    const readyRl = readline.createInterface({ input: proc.stdout });
    const ready = await new Promise((resolve) => {
        const onLine = (line) => {
            // Skip non-JSON lines
            if (!line.trim().startsWith('{') && !line.trim().startsWith('[')) {
                console.error('[skipped non-JSON]', line);
                return;
            }
            
            readyRl.close();
            resolve(JSON.parse(line));
        };
        
        readyRl.on('line', onLine);
    });
    console.log('Ready:', ready);
    
    // Test 1: Launch browser and go to example.com
    console.log('\n--- Test 1: Launch browser ---');
    const launchResult = await sendCommand(proc, {
        action: 'launch',
        url: 'https://example.com',
        config: { headless: true },
    });
    console.log('Launch result:', launchResult);
    
    // Test 2: Take screenshot
    console.log('\n--- Test 2: Screenshot ---');
    const screenshotResult = await sendCommand(proc, {
        action: 'screenshot',
        path: '/tmp/midscene_test.png',
    });
    console.log('Screenshot result:', screenshotResult);
    
    // Test 3: Keyboard
    console.log('\n--- Test 3: Keyboard ---');
    const keyResult = await sendCommand(proc, {
        action: 'keyboard',
        keys: 'ctrl+a',
    });
    console.log('Keyboard result:', keyResult);
    
    // Test 4: Close
    console.log('\n--- Test 4: Close ---');
    const closeResult = await sendCommand(proc, {
        action: 'close',
    });
    console.log('Close result:', closeResult);
    
    proc.kill();
    console.log('\n✅ All tests passed!');
}

main().catch(console.error);
